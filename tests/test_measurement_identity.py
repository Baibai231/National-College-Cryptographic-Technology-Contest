import unittest
from unittest import mock

from utils import util_str_generator as generator


class MeasurementIdentityTests(unittest.TestCase):
    def test_default_address_cannot_deliver_to_a_real_mailbox(self):
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("secrets.token_hex", return_value="0123456789abcdef"):
            address, metadata = generator.gen_measurement_email()

        self.assertEqual(address, "cryptoscope-0123456789abcdef@example.invalid")
        self.assertEqual(metadata["mode"], "reserved_non_delivery")
        self.assertFalse(metadata["mail_delivery_configured"])

    def test_catch_all_domain_generates_unique_local_part(self):
        environment = {
            "SITES_MEASURE_EMAIL_DOMAIN": "research.example.org",
            "SITES_MEASURE_EMAIL_PREFIX": "Crypto Scope",
        }
        with mock.patch.dict("os.environ", environment, clear=True), \
                mock.patch("secrets.token_hex", return_value="fedcba9876543210"):
            address, metadata = generator.gen_measurement_email()

        self.assertEqual(
            address, "crypto-scope-fedcba9876543210@research.example.org")
        self.assertEqual(metadata["mode"], "configured_catch_all")
        self.assertTrue(metadata["unique_per_run"])

    def test_fixed_address_is_used_only_when_valid(self):
        environment = {"SITES_MEASURE_EMAIL_ADDRESS": "lab@example.org"}
        with mock.patch.dict("os.environ", environment, clear=True):
            address, metadata = generator.gen_measurement_email()

        self.assertEqual(address, "lab@example.org")
        self.assertEqual(metadata["mode"], "configured_fixed")
        self.assertFalse(metadata["unique_per_run"])

    def test_invalid_config_falls_back_to_reserved_domain(self):
        environment = {
            "SITES_MEASURE_EMAIL_ADDRESS": "bad address@example.org",
            "SITES_MEASURE_EMAIL_DOMAIN": "localhost",
        }
        with mock.patch.dict("os.environ", environment, clear=True):
            address, metadata = generator.gen_measurement_email()

        self.assertTrue(address.endswith("@example.invalid"))
        self.assertEqual(metadata["mode"], "reserved_non_delivery")


if __name__ == "__main__":
    unittest.main()
