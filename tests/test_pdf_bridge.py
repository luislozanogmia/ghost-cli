import asyncio
import unittest

from aiohttp import ClientSession, web

from bridge_server import BridgeServer
from tests.test_pdf_reader import make_text_pdf


class PdfBridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pdf_upload_token_is_loopback_and_one_time(self):
        server = BridgeServer()
        token = "single-use-token"
        upload_future = server.pending_pdf_uploads[token] = asyncio.get_running_loop().create_future()
        app = web.Application()
        app.router.add_post("/pdf-upload/{token}", server.handle_pdf_upload)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = runner.addresses[0][1]
        url = f"http://127.0.0.1:{port}/pdf-upload/{token}"
        pdf_bytes = make_text_pdf("one time")

        try:
            async with ClientSession() as client:
                first = await client.post(
                    url,
                    data=pdf_bytes,
                    headers={"X-Ghost-PDF-Token": token},
                )
                self.assertEqual(first.status, 200)
                self.assertEqual(await upload_future, pdf_bytes)
                second = await client.post(
                    url,
                    data=pdf_bytes,
                    headers={"X-Ghost-PDF-Token": token},
                )
                self.assertEqual(second.status, 404)
        finally:
            await runner.cleanup()

    async def test_pdf_read_combines_fetch_metadata_and_extraction(self):
        server = BridgeServer(port=9377)
        pdf_bytes = make_text_pdf("Bridge PDF text")

        async def fake_send(command, args, timeout):
            self.assertEqual(command, "ghost_pdf_fetch")
            self.assertEqual(args["max_bytes"], 50 * 1024 * 1024)
            self.assertEqual(
                args["upload_url"],
                f"http://127.0.0.1:9378/pdf-upload/{args['upload_token']}",
            )
            server.pending_pdf_uploads[args["upload_token"]].set_result(pdf_bytes)
            return {
                "result": {
                    "url": "https://example.com/report.pdf",
                    "title": "Report",
                    "content_type": "application/pdf",
                }
            }

        server.send_command = fake_send
        result = await server.handle_pdf_read(
            {"page_start": 1, "page_end": 1, "mode": "auto"}, 10
        )

        self.assertEqual(result["url"], "https://example.com/report.pdf")
        self.assertEqual(result["pages"][0]["source"], "embedded_text")
        self.assertIn("Bridge PDF text", result["pages"][0]["text"])
        self.assertEqual(len(result["sha256"]), 64)
        self.assertEqual(result["bytes"], len(pdf_bytes))
        self.assertEqual(server.pending_pdf_uploads, {})

    async def test_pdf_read_rejects_bad_mode_before_contacting_extension(self):
        server = BridgeServer()
        with self.assertRaisesRegex(Exception, "INVALID_MODE"):
            await server.handle_pdf_read({"mode": "unknown"}, 10)


if __name__ == "__main__":
    unittest.main()
