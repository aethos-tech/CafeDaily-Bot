"""CaféDaily forms using live project questions and the Hub as the source of truth."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import discord

from src.hub_bridge import HubBridge, HubError

logger = logging.getLogger(__name__)
NO_MENTIONS = discord.AllowedMentions.none()


def parse_boolean(value: str) -> bool:
    normalized = value.strip().casefold()
    if normalized == "sim":
        return True
    if normalized in {"não", "nao"}:
        return False
    raise HubError("Nas perguntas de Sim / Não, responda apenas Sim ou Não.")


def daily_fields(questions: list[dict]) -> list[dict]:
    return [*[{**question, "key": "question:" + question["id"]} for question in questions], {"id": "__blocker", "key": "system:blocker", "label": "Você tem algum bloqueio?", "type": "BOOLEAN", "required": True}, {"id": "__blocker_details", "key": "system:blocker_details", "label": "Detalhes do bloqueio (se houver)", "type": "TEXT", "required": False}]


def field_pages(questions: list[dict]) -> list[list[dict]]:
    fields = daily_fields(questions)
    return [fields[index:index + 5] for index in range(0, len(fields), 5)]


@dataclass
class DailyDraft:
    bridge: HubBridge
    project_id: str
    guild_id: str
    discord_id: str
    form: dict
    values: dict[str, str] = field(default_factory=dict)
    page: int = 0

    def __post_init__(self) -> None:
        previous = self.form.get("report") or {}
        for answer in previous.get("answers", []):
            value = answer.get("value", "")
            self.values["question:" + answer["questionId"]] = ("Sim" if value else "Não") if isinstance(value, bool) else str(value)
        if previous:
            self.values["system:blocker"] = "Sim" if previous.get("hasBlocker") else "Não"
            self.values["system:blocker_details"] = previous.get("blockerDetails") or ""

    @property
    def pages(self) -> list[list[dict]]:
        return field_pages(self.form["config"]["questions"])

    def prompt(self) -> str:
        questions = "\n".join(f"• {question['label']}" for question in self.pages[self.page])
        return f"**Etapa {self.page + 1} de {len(self.pages)}**\n{questions}"

    def submission(self) -> dict:
        answers = []
        for question in self.form["config"]["questions"]:
            value = self.values.get("question:" + question["id"], "").strip()
            if not value and not question["required"]:
                continue
            if not value:
                raise HubError(f"Responda: {question['label']}")
            answers.append({"questionId": question["id"], "value": parse_boolean(value) if question["type"] == "BOOLEAN" else value})
        blocker = parse_boolean(self.values.get("system:blocker", ""))
        details = self.values.get("system:blocker_details", "").strip()
        if blocker and not details:
            raise HubError("Você informou um bloqueio. Descreva o impedimento no campo de detalhes.")
        return {"answers": answers, "hasBlocker": blocker, "blockerDetails": details if blocker else ""}


class DailyStepView(discord.ui.View):
    def __init__(self, draft: DailyDraft) -> None:
        super().__init__(timeout=900)
        self.draft = draft
        button = discord.ui.Button(label=f"Preencher etapa {draft.page + 1} de {len(draft.pages)}", style=discord.ButtonStyle.primary)
        button.callback = self.open_form
        self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.draft.discord_id:
            await interaction.response.send_message("Este formulário pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    async def open_form(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(HubDailyModal(self.draft))


class HubDailyModal(discord.ui.Modal):
    def __init__(self, draft: DailyDraft) -> None:
        super().__init__(title=f"Daily · etapa {draft.page + 1}/{len(draft.pages)}", timeout=900)
        self.draft = draft
        self.inputs: dict[str, discord.ui.TextInput] = {}
        for question in draft.pages[draft.page]:
            boolean = question["type"] == "BOOLEAN"
            field = discord.ui.TextInput(label=question["label"][:45], custom_id=f"q{len(self.inputs)}", style=discord.TextStyle.short if boolean else discord.TextStyle.paragraph, required=question["required"], max_length=3 if boolean else 4000, placeholder="Sim ou Não" if boolean else question["label"][:100], default=draft.values.get(question["key"], "")[:4000])
            self.inputs[question["key"]] = field
            self.add_item(field)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        for question_id, field in self.inputs.items():
            self.draft.values[question_id] = str(field.value).strip()
        try:
            for question in self.draft.pages[self.draft.page]:
                value = self.draft.values[question["key"]]
                if question["type"] == "BOOLEAN" and value:
                    parse_boolean(value)
            if self.draft.page < len(self.draft.pages) - 1:
                self.draft.page += 1
                await interaction.followup.send("Etapa salva neste formulário. Continue para finalizar o envio ao Hub.\n\n" + self.draft.prompt(), view=DailyStepView(self.draft), ephemeral=True, allowed_mentions=NO_MENTIONS)
                return
            submission = self.draft.submission()
            await self.draft.bridge.project(self.draft.project_id, "submit", {"guildId": self.draft.guild_id, "discordId": self.draft.discord_id, "revision": self.draft.form["revision"], "reportDate": self.draft.form["reportDate"], "submission": submission})
        except HubError as exc:
            await interaction.followup.send(str(exc), view=DailyStepView(self.draft), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        except Exception:
            logger.error("Hub daily submission failed")
            await interaction.followup.send("Não consegui confirmar o envio. Tente novamente pelo botão do daily.", ephemeral=True)
            return
        name = discord.utils.escape_markdown(self.draft.form["projectName"])
        await interaction.followup.send(f"✅ Daily de **{name}** salvo no Hub. Sua liderança já pode acompanhar o relatório e o horário do envio.", ephemeral=True, allowed_mentions=NO_MENTIONS)


class DailyProjectPickerView(discord.ui.View):
    """Private, paginated project choices; the API rechecks access on selection."""

    def __init__(self, bridge: HubBridge, guild_id: str | None, discord_id: str, projects: list[dict], channel_id: str | None = None) -> None:
        super().__init__(timeout=900)
        self.bridge = bridge
        self.guild_id = guild_id
        self.discord_id = discord_id
        self.projects = projects
        self.channel_id = channel_id
        self.page = 0
        self.render()

    def prompt(self) -> str:
        text = "**Em qual projeto você quer registrar o daily?**\nSelecione um projeto abaixo. Só você vê esta seleção e o formulário."
        if len(self.projects) > 25:
            text += f"\n\nPágina {self.page + 1} de {(len(self.projects) + 24) // 25}"
        return text

    def render(self) -> None:
        self.clear_items()
        page = self.projects[self.page * 25:(self.page + 1) * 25]
        self.select = discord.ui.Select(placeholder="Selecione o projeto do daily", min_values=1, max_values=1, options=[discord.SelectOption(label=project["projectName"][:100] or "Projeto sem nome", value=project["projectId"]) for project in page])
        self.select.callback = self.choose_project
        self.add_item(self.select)
        if len(self.projects) > 25:
            previous = discord.ui.Button(label="Anterior", disabled=self.page == 0, row=1)
            previous.callback = self.previous_page
            following = discord.ui.Button(label="Próxima", disabled=(self.page + 1) * 25 >= len(self.projects), row=1)
            following.callback = self.next_page
            self.add_item(previous)
            self.add_item(following)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if str(interaction.user.id) != self.discord_id or (interaction.guild_id is not None and str(interaction.guild_id) != self.guild_id):
            await interaction.response.send_message("Esta seleção pertence a outra pessoa ou servidor.", ephemeral=True)
            return False
        return True

    async def previous_page(self, interaction: discord.Interaction) -> None:
        self.page = max(0, self.page - 1)
        self.render()
        await interaction.response.edit_message(content=self.prompt(), view=self, allowed_mentions=NO_MENTIONS)

    async def next_page(self, interaction: discord.Interaction) -> None:
        self.page = min((len(self.projects) - 1) // 25, self.page + 1)
        self.render()
        await interaction.response.edit_message(content=self.prompt(), view=self, allowed_mentions=NO_MENTIONS)

    async def choose_project(self, interaction: discord.Interaction) -> None:
        await self.open_project(interaction, self.select.values[0])

    async def open_project(self, interaction: discord.Interaction, project_id: str) -> None:
        if not any(project["projectId"] == project_id for project in self.projects):
            await interaction.response.send_message("Selecione um dos projetos disponíveis no menu.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        selected = next(project for project in self.projects if project["projectId"] == project_id)
        guild_id = self.guild_id or selected["guildId"]
        payload = {"guildId": guild_id, "discordId": str(interaction.user.id)}
        if self.channel_id is not None:
            payload["channelId"] = self.channel_id
        try:
            form = await self.bridge.project(project_id, "form", payload)
        except HubError as exc:
            await interaction.followup.send(str(exc), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        previous = form.get("report") or {}
        if any(isinstance(answer.get("value"), str) and len(answer["value"]) > 4000 for answer in previous.get("answers", [])) or len(previous.get("blockerDetails") or "") > 4000:
            await interaction.followup.send("Este daily contém respostas maiores que o limite do Discord. Para preservar o conteúdo, atualize este relatório pelo Hub.", ephemeral=True)
            return
        draft = DailyDraft(self.bridge, project_id, guild_id, str(interaction.user.id), form)
        name = discord.utils.escape_markdown(form["projectName"])
        await interaction.followup.send(f"**Daily · {name}**\nPreencha as perguntas do projeto. Só você vê este formulário. O envio final ficará disponível para a liderança no Hub.\n\n{draft.prompt()}", view=DailyStepView(draft), ephemeral=True, allowed_mentions=NO_MENTIONS)


class HubDailyPanelView(discord.ui.View):
    def __init__(self, project_id: str | None, bridge: HubBridge, projects: dict[str, dict]) -> None:
        super().__init__(timeout=None)
        self.project_id = project_id
        self.bridge = bridge
        self.projects = projects
        button = discord.ui.Button(label="Registrar Daily", style=discord.ButtonStyle.primary, custom_id=f"hub:daily:{project_id}" if project_id else "hub:daily:register")
        button.callback = self.open_daily
        self.add_item(button)

    async def open_daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        project = self.projects.get(self.project_id) if self.project_id else None
        guild_id = str(interaction.guild_id) if interaction.guild_id is not None else project["guildId"] if project else None
        if guild_id is None:
            await interaction.followup.send("Este daily foi desativado. Confira a configuração do projeto no Hub.", ephemeral=True)
            return
        payload = {"guildId": guild_id, "discordId": str(interaction.user.id)}
        channel_id = str(interaction.channel_id) if interaction.guild_id is not None else None
        if interaction.guild_id is not None:
            payload["channelId"] = channel_id
        try:
            result = await self.bridge.request("POST", "/projects", payload)
        except HubError as exc:
            await interaction.followup.send(str(exc), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        if not result["projects"]:
            await interaction.followup.send("Nenhum projeto disponível para registrar daily. Você precisa participar de um projeto com o daily e a integração do Discord habilitados neste servidor.", ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        view = DailyProjectPickerView(self.bridge, guild_id, str(interaction.user.id), result["projects"], channel_id)
        await interaction.followup.send(view.prompt(), view=view, ephemeral=True, allowed_mentions=NO_MENTIONS)


async def open_daily_command(interaction: discord.Interaction, bridge: HubBridge) -> None:
    """Open private choices from any guild channel or the bot DM."""
    await interaction.response.defer(ephemeral=True)
    guild_id = str(interaction.guild_id) if interaction.guild_id is not None else None
    payload = {"discordId": str(interaction.user.id)}
    if guild_id is not None:
        payload["guildId"] = guild_id
    try:
        result = await bridge.request("POST", "/projects", payload)
    except HubError as exc:
        await interaction.followup.send(str(exc), ephemeral=True, allowed_mentions=NO_MENTIONS)
        return
    if not result["projects"]:
        await interaction.followup.send("Nenhum projeto disponível. Confira seu vínculo com o Hub e sua participação em um projeto com daily e Discord habilitados.", ephemeral=True, allowed_mentions=NO_MENTIONS)
        return
    view = DailyProjectPickerView(bridge, guild_id, str(interaction.user.id), result["projects"])
    await interaction.followup.send(view.prompt(), view=view, ephemeral=True, allowed_mentions=NO_MENTIONS)
