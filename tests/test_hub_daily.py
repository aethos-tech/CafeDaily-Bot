import secrets
import unittest
from unittest.mock import AsyncMock

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer

from src.hub_bridge import HubBridge, HubError
from src.hub_daily import DailyDraft, HubDailyModal, field_pages, parse_boolean
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


if __name__ == "__main__":
    unittest.main()
