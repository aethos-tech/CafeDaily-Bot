"""Hub-managed CaféDaily runtime; project configuration is pulled from the Hub."""
from __future__ import annotations

import asyncio
import logging
import os

import aiohttp
import discord
from discord import app_commands

from src.hub_bridge import HubBridge, HubError
from src.hub_daily import HubDailyPanelView, NO_MENTIONS

logger = logging.getLogger(__name__)


class HubDailyBot(discord.Client):
    def __init__(self, bridge: HubBridge, revision: str) -> None:
        super().__init__(intents=discord.Intents(guilds=True), allowed_mentions=NO_MENTIONS)
        self.bridge = bridge
        self.revision = revision
        self.tree = app_commands.CommandTree(self)
        self.projects: dict[str, dict] = {}
        self.registered_views: set[str] = set()
        self.poll_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        @app_commands.guild_only()
        @app_commands.describe(codigo="Código temporário gerado na aba Daily report do Hub")
        async def link(interaction: discord.Interaction, codigo: str) -> None:
            await interaction.response.defer(ephemeral=True)
            codigo = codigo.strip()
            project_id = codigo.split(".", 1)[0]
            project = self.projects.get(project_id)
            if not project or str(interaction.guild_id) != project["guildId"]:
                await interaction.followup.send("Use o código no servidor configurado para o projeto e confirme que o daily está ativo.", ephemeral=True)
                return
            try:
                await self.bridge.project(project_id, "link", {"guildId": project["guildId"], "discordId": str(interaction.user.id), "displayName": interaction.user.display_name, "code": codigo.strip()})
            except HubError as exc:
                await interaction.followup.send(str(exc), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            await interaction.followup.send("✅ Conta vinculada ao Hub. Agora você pode usar o botão Registrar Daily. Os lembretes por DM podem ser desativados no Hub.", ephemeral=True)

        self.tree.add_command(app_commands.Command(name="hub-vincular", description="Vincular sua conta do Discord ao Kina Hub", callback=link))
        await self.tree.sync()
        self.poll_task = asyncio.create_task(self.poll())

    async def on_ready(self) -> None:
        logger.info("CaféDaily connected to Discord; project configuration is managed by the Hub")

    async def poll(self) -> None:
        await self.wait_until_ready()
        iteration = 0
        while not self.is_closed():
            try:
                catalog = await self.bridge.request("POST", "/catalog", {"revision": self.revision})
                if catalog.get("restart"):
                    await self.close()
                    return
                self.projects.clear()
                self.projects.update({project["projectId"]: project for project in catalog["projects"]})
                for project in list(self.projects.values()):
                    project_id = project["projectId"]
                    if project_id not in self.registered_views:
                        self.add_view(HubDailyPanelView(project_id, self.bridge, self.projects))
                        self.registered_views.add(project_id)
                    if project["panelRevision"] > project["deliveredRevision"]:
                        await self.publish_panel(project)
                    if iteration % 3 == 0:
                        await self.remind(project)
                iteration += 1
            except HubError:
                logger.warning("Hub is temporarily unavailable; integration will retry")
            except Exception:
                logger.error("Hub integration cycle failed; it will retry")
            await asyncio.sleep(20)

    async def publish_panel(self, project: dict) -> None:
        project_id = project["projectId"]
        payload = {"guildId": project["guildId"], "revision": project["panelRevision"]}
        claim = await self.bridge.project(project_id, "panel/claim", payload)
        if not claim.get("claimId"):
            return
        message_id = None
        error = None
        try:
            channel = self.get_channel(int(project["channelId"])) or await self.fetch_channel(int(project["channelId"]))
            if not isinstance(channel, (discord.TextChannel, discord.Thread)) or str(channel.guild.id) != project["guildId"]:
                raise ValueError("Channel does not belong to configured guild")
            embed = discord.Embed(title=f"Daily report · {project['projectName']}"[:256], description="Compartilhe avanços, planos e bloqueios sem sair do Discord.\n\n**Primeiro acesso:** gere um código na aba Daily report do Hub e use `/hub-vincular`. Depois, clique em **Registrar Daily**.\n\nAs respostas são privadas e ficam organizadas para a liderança no Hub.", color=0xFED813)
            embed.set_footer(text="CaféDaily + Kina Hub")
            view = HubDailyPanelView(project_id, self.bridge, self.projects)
            previous = None
            if project.get("panelMessageId"):
                try:
                    previous = await channel.fetch_message(int(project["panelMessageId"]))
                except discord.NotFound:
                    previous = None
            message = await previous.edit(embed=embed, view=view, allowed_mentions=NO_MENTIONS) if previous else await channel.send(embed=embed, view=view, allowed_mentions=NO_MENTIONS)
            message_id = str(message.id)
        except discord.Forbidden:
            error = "FORBIDDEN"
        except (discord.NotFound, ValueError):
            error = "CHANNEL_NOT_FOUND"
        except discord.HTTPException:
            error = "UNAVAILABLE"
        await self.bridge.project(project_id, "panel/ack", {**payload, "claimId": claim["claimId"], "messageId": message_id, "error": error})

    async def remind(self, project: dict) -> None:
        project_id = project["projectId"]
        payload = {"guildId": project["guildId"]}
        claimed = await self.bridge.project(project_id, "reminders/claim", payload)
        for reminder in claimed["reminders"]:
            try:
                person = self.get_user(int(reminder["discordId"])) or await self.fetch_user(int(reminder["discordId"]))
                name = discord.utils.escape_markdown(reminder["projectName"])
                await person.send(f"☕ Hora do daily de **{name}**! Seu relatório de hoje ainda está pendente no Hub. Use o botão abaixo para responder.\n\nVocê pode desativar estes lembretes na aba Daily report do Hub.", view=HubDailyPanelView(project_id, self.bridge, self.projects), allowed_mentions=NO_MENTIONS)
            except discord.HTTPException:
                logger.warning("A daily reminder could not be delivered; Hub retry limits apply")
                continue
            await self.bridge.project(project_id, "reminders/ack", {**payload, "claimId": reminder["claimId"]})

    async def close(self) -> None:
        if self.poll_task and self.poll_task is not asyncio.current_task():
            self.poll_task.cancel()
            try:
                await self.poll_task
            except asyncio.CancelledError:
                pass
        await super().close()


async def run_hub_bot() -> None:
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        bridge = HubBridge.from_environment(session)
        while True:
            bot = None
            try:
                config = await bridge.request("GET", "/bootstrap")
                if config.get("enabled") and config.get("token"):
                    bot = HubDailyBot(bridge, config["revision"])
                    await bot.start(config["token"])
            except discord.LoginFailure:
                logger.error("CaféDaily token rejected; update it in the Hub administration panel")
                try:
                    await bridge.request("POST", "/status", {"revision": config["revision"], "error": "INVALID_TOKEN"})
                except HubError:
                    logger.warning("Could not update bot status in the Hub")
            except HubError:
                logger.warning("Waiting for Hub bot configuration")
            except Exception:
                logger.error("CaféDaily disconnected; retrying without exposing credentials")
            finally:
                if bot:
                    await bot.close()
            await asyncio.sleep(20)
