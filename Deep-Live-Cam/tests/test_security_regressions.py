import hashlib
import http.server
import inspect
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import modules.utilities as utilities


class SecurityRegressionTests(unittest.TestCase):
    def test_create_temp_rejects_preexisting_symlink_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "target.mp4"
            target.write_bytes(b"video")
            victim = Path(tmp) / "victim.txt"
            victim.write_text("safe")
            temp_dir = Path(utilities.get_temp_directory_path(str(target)))
            temp_dir.mkdir(parents=True)
            Path(utilities.get_temp_output_path(str(target))).symlink_to(victim)

            with self.assertRaises(ValueError):
                utilities.create_temp(str(target))

            self.assertEqual(victim.read_text(), "safe")

    def test_conditional_download_rejects_digest_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "model.onnx"
            source.write_bytes(b"tampered model")
            out_dir = Path(tmp) / "models"
            expected = hashlib.sha256(b"expected model").hexdigest()

            with self.assertRaises(ValueError):
                utilities.conditional_download(
                    str(out_dir),
                    [source.as_uri()],
                    expected_sha256={source.as_uri(): expected},
                )

            self.assertFalse((out_dir / source.name).exists())

    def test_conditional_download_accepts_matching_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "model.onnx"
            payload = b"expected model"
            source.write_bytes(payload)
            out_dir = Path(tmp) / "models"

            utilities.conditional_download(
                str(out_dir),
                [source.as_uri()],
                expected_sha256={
                    source.as_uri(): hashlib.sha256(payload).hexdigest(),
                },
            )

            self.assertEqual((out_dir / source.name).read_bytes(), payload)

    def test_conditional_download_does_not_disable_tls_verification(self):
        self.assertNotIn(
            "_create_unverified_context",
            inspect.getsource(utilities.conditional_download),
        )

    def test_gpen_model_urls_have_sha256_pins(self):
        expected_urls = {
            "https://huggingface.co/hacksider/deep-live-cam/resolve/main/GPEN-BFR-256.onnx",
            "https://huggingface.co/hacksider/deep-live-cam/resolve/main/GPEN-BFR-512.onnx",
        }

        self.assertTrue(expected_urls.issubset(utilities.MODEL_SHA256))

    def test_gpen_precheck_rejects_existing_digest_mismatch(self):
        sys.modules["modules.utilities"] = utilities
        sys.modules.pop("modules.typing", None)
        sys.modules.pop("modules.processors.frame.face_enhancer_gpen512", None)
        import modules.processors.frame.face_enhancer_gpen512 as gpen512

        with tempfile.TemporaryDirectory() as tmp:
            source_dir = Path(tmp) / "source"
            source_dir.mkdir()
            model_dir = Path(tmp) / "models"
            model_dir.mkdir()
            source = source_dir / "GPEN-BFR-512.onnx"
            source.write_bytes(b"expected model")
            existing = model_dir / "GPEN-BFR-512.onnx"
            existing.write_bytes(b"tampered model")

            old_models_dir = gpen512.models_dir
            old_model_url = gpen512.MODEL_URL
            old_model_file = gpen512.MODEL_FILE
            old_sha = utilities.MODEL_SHA256.copy()
            try:
                gpen512.models_dir = str(model_dir)
                gpen512.MODEL_URL = source.as_uri()
                gpen512.MODEL_FILE = existing.name
                utilities.MODEL_SHA256[source.as_uri()] = hashlib.sha256(
                    b"expected model"
                ).hexdigest()

                self.assertFalse(gpen512.pre_check())
            finally:
                gpen512.models_dir = old_models_dir
                gpen512.MODEL_URL = old_model_url
                gpen512.MODEL_FILE = old_model_file
                utilities.MODEL_SHA256.clear()
                utilities.MODEL_SHA256.update(old_sha)


class OversizedBodyHandler(http.server.BaseHTTPRequestHandler):
    body = b"x" * 64

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *_args):
        return


class RandomFaceDownloadTests(unittest.TestCase):
    def test_random_face_download_rejects_oversized_response(self):
        import modules.ui as ui

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OversizedBodyHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}/face.jpg"
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):
                    ui.download_random_face_image(
                        url=url,
                        destination_dir=tmp,
                        max_bytes=8,
                    )
        finally:
            server.shutdown()
            thread.join()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
