"""Unit tests for the POS HTTP REST API server."""

import json
import unittest
from unittest.mock import patch, MagicMock
from pos.server import PosApiHandler


class TestServerHandler(unittest.TestCase):
    def test_health_check(self):
        handler = PosApiHandler.__new__(PosApiHandler)
        handler.path = "/health"
        handler._send_json = MagicMock()

        handler.do_GET()

        handler._send_json.assert_called_once()
        code, data = handler._send_json.call_args[0]
        self.assertEqual(code, 200)
        self.assertEqual(data.get("status"), "ok")


if __name__ == "__main__":
    unittest.main()
