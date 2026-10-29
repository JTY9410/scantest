from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PostgresSeedInitTest(unittest.TestCase):
    def test_postgres_seed_init_scripts_are_present_and_executable(self):
        restore_script = ROOT / "docker/postgres/init/10-restore-seed.sh"
        test_db_script = ROOT / "docker/postgres/init/20-create-test-db.sh"
        export_script = ROOT / "scripts/export_supabase_seed.sh"

        self.assertTrue(restore_script.exists())
        self.assertTrue(test_db_script.exists())
        self.assertTrue(export_script.exists())

        self.assertTrue(restore_script.stat().st_mode & 0o111)
        self.assertTrue(test_db_script.stat().st_mode & 0o111)
        self.assertTrue(export_script.stat().st_mode & 0o111)

        restore_contents = restore_script.read_text()
        self.assertIn("set -eu", restore_contents)
        self.assertIn("/seed/supabase_baseline.dump", restore_contents)
        self.assertIn("pg_restore", restore_contents)
        self.assertIn("--no-owner", restore_contents)
        self.assertIn("--no-acl", restore_contents)
        self.assertIn('--role="$POSTGRES_USER"', restore_contents)

        export_contents = export_script.read_text()
        self.assertIn("SUPABASE_DATABASE_URL", export_contents)
        self.assertIn("pg_dump", export_contents)
        self.assertIn("-Fc", export_contents)
        self.assertIn("--schema=public", export_contents)
        self.assertIn("--no-owner", export_contents)
        self.assertIn("--no-acl", export_contents)
        self.assertIn("data/seed/supabase_baseline.dump", export_contents)

    def test_compose_mounts_init_directory_and_seed_readonly(self):
        expected_mounts = [
            "./docker/postgres/init:/docker-entrypoint-initdb.d:ro",
            "./data/seed:/seed:ro",
        ]

        for compose_file in ("compose.yaml", "compose.prod.yaml"):
            contents = (ROOT / compose_file).read_text()
            for mount in expected_mounts:
                self.assertIn(mount, contents)
            self.assertNotIn("init-test-db.sh:/docker-entrypoint-initdb.d", contents)

        self.assertFalse((ROOT / "docker/postgres/init-test-db.sh").exists())


if __name__ == "__main__":
    unittest.main()
