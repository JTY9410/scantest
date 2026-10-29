from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class WebAutoDbUpgradeTest(unittest.TestCase):
    def test_web_entrypoint_runs_db_upgrade_when_enabled(self):
        entrypoint = ROOT / "docker/web-entrypoint.sh"

        self.assertTrue(entrypoint.exists())
        self.assertTrue(entrypoint.stat().st_mode & 0o111)

        contents = entrypoint.read_text()
        self.assertIn("set -eu", contents)
        self.assertIn("AUTO_DB_UPGRADE", contents)
        self.assertIn("flask db upgrade", contents)
        self.assertIn('exec "$@"', contents)

    def test_dockerfile_uses_entrypoint_without_replacing_cmd(self):
        contents = (ROOT / "Dockerfile").read_text()

        self.assertIn("COPY --chmod=755 docker/web-entrypoint.sh", contents)
        self.assertEqual(contents.count('ENTRYPOINT ["/srv/docker/web-entrypoint.sh"]'), 2)
        self.assertIn('CMD ["flask", "run"', contents)
        self.assertIn('CMD ["gunicorn"', contents)
        self.assertIn("ADR 0002", contents)
        self.assertNotIn("시작 시 DB 이전을 자동 실행하지 않는다", contents)

    def test_compose_mac_and_prod_enable_auto_db_upgrade(self):
        for compose_file in ("compose.mac.yaml", "compose.prod.yaml"):
            contents = (ROOT / compose_file).read_text()

            self.assertIn("AUTO_DB_UPGRADE: \"1\"", contents)

    def test_auto_db_upgrade_adr_exists(self):
        adr = ROOT / "docs/adr/0002-auto-db-upgrade-on-boot.md"

        self.assertTrue(adr.exists())
        contents = adr.read_text()
        self.assertIn("AUTO_DB_UPGRADE", contents)
        self.assertIn("pro.md", contents)
        self.assertIn("Mac", contents)
        self.assertIn("Compose", contents)


if __name__ == "__main__":
    unittest.main()
