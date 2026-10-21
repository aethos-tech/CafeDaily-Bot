import secrets
import unittest
from unittest.mock import AsyncMock
from types import SimpleNamespace

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.hub_bridge import HubBridge, HubError
from src.hub_daily import DailyDraft, DailyProjectPickerView, DailyStepView, HubDailyModal, HubDailyPanelView, field_pages, parse_boolean
from src.hub_main import HubDailyBot


def form(questions=None):
    return {"projectName": "Projeto de teste", "revision": "2026-10-19T12:00:00.000Z", "reportDate": "2026-10-19", "config": {"questions": questions or [{"id": "yesterday", "label": "O que fez ontem?", "type": "TEXT", "required": True}]}, "report": None}


class DailyFormTests(unittest.TestCase):
    def test_boolean_is_explicit_and_accent_insensitive(self):
        self.assertTrue(parse_boolean(" Sim "))
        self.assertFalse(parse_boolean("NÃO"))
        self.assertFalse(parse_boolean("nao"))
        for value in ["talvez", "", "sim ou não"]:
            with self.assertRaises(HubError):
                parse_boolean(value)

    def test_all_project_questions_and_blockers_fit_discord_pages(self):
        questions = [{"id": str(i), "label": "Pergunta", "type": "TEXT", "required": True} for i in range(12)]
        pages = field_pages(questions)
        self.assertEqual([len(page) for page in pages], [5, 5, 4])
        self.assertEqual(len({item["key"] for page in pages for item in page}), 14)

    def test_project_question_ids_cannot_override_the_blocker_fields(self):
        draft = DailyDraft(AsyncMock(), "project", "guild", "person", form([{"id": "__blocker", "label": "Uma pergunta", "type": "TEXT", "required": True}]))
        draft.values = {"question:__blocker": "Resposta da pergunta", "system:blocker": "Não", "system:blocker_details": ""}
        result = draft.submission()
        self.assertFalse(result["hasBlocker"])
        self.assertEqual(result["answers"][0]["value"], "Resposta da pergunta")

    def test_preloads_an_existing_report_for_updates(self):
        initial = form()
        initial["report"] = {"answers": [{"questionId": "yesterday", "value": "Trabalho de ontem"}], "hasBlocker": True, "blockerDetails": "Aguardando acesso"}
        draft = DailyDraft(AsyncMock(), "project", "guild", "person", initial)
        self.assertEqual(draft.submission(), {"answers": [{"questionId": "yesterday", "value": "Trabalho de ontem"}], "hasBlocker": True, "blockerDetails": "Aguardando acesso"})

    def test_requires_blocker_details_and_does_not_treat_optional_false_as_missing(self):
        draft = DailyDraft(AsyncMock(), "project", "guild", "person", form([{"id": "ready", "label": "Pronto?", "type": "BOOLEAN", "required": False}]))
        draft.values = {"question:ready": "Não", "system:blocker": "Sim", "system:blocker_details": ""}
        with self.assertRaises(HubError):
            draft.submission()
        draft.values["system:blocker_details"] = "Ambiente fora do ar"
        self.assertIs(draft.submission()["answers"][0]["value"], False)


class DiscordModalTests(unittest.IsolatedAsyncioTestCase):
    async def test_modals_respect_discord_field_and_label_limits(self):
        draft = DailyDraft(AsyncMock(), "project", "guild", "person", form([{"id": "yesterday", "label": "Pergunta muito longa " * 12, "type": "TEXT", "required": True}]))
        modal = HubDailyModal(draft)
        self.assertLessEqual(len(modal.children), 5)
        self.assertTrue(all(len(child.label) <= 45 for child in modal.children))
        self.assertTrue(all(child.max_length <= 4000 for child in modal.children))

    async def test_client_needs_no_privileged_message_content_intent(self):
        bot = HubDailyBot(AsyncMock(), "revision")
        self.assertTrue(bot.intents.guilds)
        self.assertFalse(bot.intents.message_content)
        self.assertFalse(bot.intents.members)
        await bot.close()


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bridge_authenticates_and_uses_the_project_endpoint(self):
        key = secrets.token_hex(32)
        received = []
        async def handler(request):
            received.append((request.headers.get("Authorization"), await request.json()))
            return web.json_response({"ok": True})
        app = web.Application()
        app.router.add_post("/api/daily-discord/bridge/projects/project/submit", handler)
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            bridge = HubBridge(session, str(server.make_url("/")), key)
            self.assertEqual(await bridge.project("project", "submit", {"discordId": "person"}), {"ok": True})
        self.assertEqual(received, [(f"Bearer {key}", {"discordId": "person"})])

    async def test_uses_the_hub_validation_message_without_confirming_a_failed_save(self):
        async def handler(_request):
            return web.json_response({"error": "Forbidden", "message": "Seu acesso ao projeto foi removido"}, status=403)
        app = web.Application()
        app.router.add_post("/api/daily-discord/bridge/projects/project/submit", handler)
        async with TestServer(app) as server, aiohttp.ClientSession() as session:
            bridge = HubBridge(session, str(server.make_url("/")), secrets.token_hex(32))
            with self.assertRaisesRegex(HubError, "Seu acesso ao projeto foi removido"):
                await bridge.project("project", "submit", {})

    async def test_refuses_a_plain_http_external_destination(self):
        async with aiohttp.ClientSession() as session:
            with self.assertRaises(ValueError):
                HubBridge(session, "http://external.example.invalid", secrets.token_hex(32))


def interaction(user_id=333333333333333333, guild_id=111111111111111111):
    return SimpleNamespace(user=SimpleNamespace(id=user_id), guild_id=guild_id, channel_id=222222222222222222, response=AsyncMock(), followup=AsyncMock())


class ProjectSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.bridge = AsyncMock(spec=HubBridge)
        self.projects = [{"projectId": "alpha", "projectName": "Alfa"}, {"projectId": "beta", "projectName": "Beta"}]
        self.bridge.request.return_value = {"projects": self.projects}
        self.bridge.project.return_value = form()

    async def test_persistent_panel_shows_private_choices_before_loading_any_report(self):
        panel = HubDailyPanelView(None, self.bridge, {})
        self.assertTrue(panel.is_persistent())
        event = interaction()
        await panel.open_daily(event)
        self.bridge.request.assert_awaited_once_with("POST", "/projects", {"guildId": "111111111111111111", "discordId": "333333333333333333", "channelId": "222222222222222222"})
        self.bridge.project.assert_not_awaited()
        sent = event.followup.send.call_args.kwargs
        self.assertTrue(sent["ephemeral"])
        self.assertIsInstance(sent["view"], DailyProjectPickerView)
        self.assertEqual([option.value for option in sent["view"].select.options], ["alpha", "beta"])

    async def test_old_project_button_can_choose_other_projects_even_after_its_project_is_disabled(self):
        panel = HubDailyPanelView("old-project", self.bridge, {})
        await panel.open_daily(interaction())
        self.assertIsInstance(self.bridge.request.call_args.args[2], dict)
        self.bridge.project.assert_not_awaited()

    async def test_unlinked_account_and_no_active_projects_do_not_open_a_form(self):
        panel = HubDailyPanelView(None, self.bridge, {})
        self.bridge.request.side_effect = HubError("Vincule seu Discord em Minha conta → Integrações no Hub antes de continuar")
        event = interaction()
        await panel.open_daily(event)
        self.assertIn("Integrações", event.followup.send.call_args.args[0])
        self.assertNotIn("view", event.followup.send.call_args.kwargs)
        self.bridge.request.side_effect = None
        self.bridge.request.return_value = {"projects": []}
        await panel.open_daily(event)
        self.assertIn("Nenhum projeto", event.followup.send.call_args.args[0])
        self.assertNotIn("view", event.followup.send.call_args.kwargs)
        self.bridge.project.assert_not_awaited()

    async def test_dm_button_uses_its_approved_guild_without_a_public_channel(self):
        panel = HubDailyPanelView("alpha", self.bridge, {"alpha": {"guildId": "111111111111111111"}})
        event = interaction(guild_id=None)
        await panel.open_daily(event)
        self.assertEqual(self.bridge.request.call_args.args[2], {"guildId": "111111111111111111", "discordId": "333333333333333333"})
        self.assertTrue(event.followup.send.call_args.kwargs["ephemeral"])

    async def test_project_menu_is_bound_to_the_person_and_guild(self):
        menu = DailyProjectPickerView(self.bridge, "111111111111111111", "333333333333333333", self.projects)
        self.assertFalse(await menu.interaction_check(interaction(user_id=999999999999999999)))
        self.assertFalse(await menu.interaction_check(interaction(guild_id=999999999999999999)))
        self.assertTrue(await menu.interaction_check(interaction()))
        self.bridge.project.assert_not_awaited()

    async def test_pagination_respects_select_limits_without_hiding_projects(self):
        projects = [{"projectId": f"project-{index}", "projectName": "Nome muito longo " * 10} for index in range(51)]
        menu = DailyProjectPickerView(self.bridge, "111111111111111111", "333333333333333333", projects)
        self.assertEqual(len(menu.select.options), 25)
        self.assertTrue(all(len(option.label) <= 100 for option in menu.select.options))
        self.assertTrue(menu.children[1].disabled)
        event = interaction()
        await menu.next_page(event)
        self.assertEqual(menu.select.options[0].value, "project-25")
        self.assertEqual(len(menu.select.options), 25)
        await menu.next_page(event)
        self.assertEqual([option.value for option in menu.select.options], ["project-50"])
        self.assertTrue(menu.children[2].disabled)
        self.assertIn("Página 3 de 3", menu.prompt())
        await menu.previous_page(event)
        self.assertEqual(menu.select.options[0].value, "project-25")

    async def test_selected_project_uses_fresh_server_authorization_and_current_questions(self):
        menu = DailyProjectPickerView(self.bridge, "111111111111111111", "333333333333333333", self.projects, "222222222222222222")
        event = interaction()
        await menu.open_project(event, "beta")
        self.bridge.project.assert_awaited_once_with("beta", "form", {"guildId": "111111111111111111", "discordId": "333333333333333333", "channelId": "222222222222222222"})
        sent = event.followup.send.call_args.kwargs
        self.assertTrue(sent["ephemeral"])
        self.assertIsInstance(sent["view"], DailyStepView)
        self.assertEqual(sent["view"].draft.project_id, "beta")
        self.bridge.project.side_effect = HubError("Seu acesso foi removido ou o daily foi desativado")
        await menu.open_project(event, "beta")
        self.assertNotIn("view", event.followup.send.call_args.kwargs)

    async def test_arbitrary_project_ids_cannot_be_injected_into_the_menu(self):
        menu = DailyProjectPickerView(self.bridge, "111111111111111111", "333333333333333333", self.projects)
        event = interaction()
        await menu.open_project(event, "private-project")
        self.bridge.project.assert_not_awaited()
        event.response.send_message.assert_awaited_once()
        self.assertTrue(event.response.send_message.call_args.kwargs["ephemeral"])

    async def test_existing_panel_is_refreshed_in_place_with_native_linking_instructions(self):
        bot = HubDailyBot(self.bridge, "revision")
        message = SimpleNamespace(edit=AsyncMock())
        channel = SimpleNamespace(fetch_message=AsyncMock(return_value=message))
        bot.panel_channel = AsyncMock(return_value=channel)
        project = {"guildId": "111111111111111111", "channelId": "222222222222222222", "panelMessageId": "444444444444444444"}
        try:
            self.assertTrue(await bot.refresh_panel(project))
            channel.fetch_message.assert_awaited_once_with(444444444444444444)
            sent = message.edit.call_args.kwargs
            self.assertEqual(sent["embed"].title, "Daily report · Kina Hub")
            self.assertIn("Integrações", sent["embed"].description)
            self.assertNotIn("/hub-vincular", sent["embed"].description)
            self.assertEqual(sent["view"].children[0].custom_id, "hub:daily:register")
            self.assertTrue(sent["view"].is_persistent())
        finally:
            await bot.close()


if __name__ == "__main__":
    unittest.main()
