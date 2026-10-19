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


class HubDailyPanelView(discord.ui.View):
    def __init__(self, project_id: str, bridge: HubBridge, projects: dict[str, dict]) -> None:
        super().__init__(timeout=None)
        self.project_id = project_id
        self.bridge = bridge
        self.projects = projects
        button = discord.ui.Button(label="Registrar Daily", style=discord.ButtonStyle.primary, custom_id=f"hub:daily:{project_id}")
        button.callback = self.open_daily
        self.add_item(button)

    async def open_daily(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        project = self.projects.get(self.project_id)
        if not project:
            await interaction.followup.send("Este daily foi desativado. Confira a configuração do projeto no Hub.", ephemeral=True)
            return
        if interaction.guild_id is not None and str(interaction.guild_id) != project["guildId"]:
            await interaction.followup.send("Este painel não pertence a este servidor.", ephemeral=True)
            return
        payload = {"guildId": project["guildId"], "discordId": str(interaction.user.id)}
        if interaction.guild_id is not None:
            payload["channelId"] = str(interaction.channel_id)
        try:
            form = await self.bridge.project(self.project_id, "form", payload)
        except HubError as exc:
            await interaction.followup.send(str(exc), ephemeral=True, allowed_mentions=NO_MENTIONS)
            return
        previous = form.get("report") or {}
        if any(isinstance(answer.get("value"), str) and len(answer["value"]) > 4000 for answer in previous.get("answers", [])) or len(previous.get("blockerDetails") or "") > 4000:
            await interaction.followup.send("Este daily contém respostas maiores que o limite do Discord. Para preservar o conteúdo, atualize este relatório pelo Hub.", ephemeral=True)
            return
        draft = DailyDraft(self.bridge, self.project_id, project["guildId"], str(interaction.user.id), form)
        name = discord.utils.escape_markdown(form["projectName"])
        await interaction.followup.send(f"**Daily · {name}**\nPreencha as perguntas do projeto. Só você vê este formulário. O envio final ficará disponível para a liderança no Hub.\n\n{draft.prompt()}", view=DailyStepView(draft), ephemeral=True, allowed_mentions=NO_MENTIONS)
