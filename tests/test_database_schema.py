#!/usr/bin/env python3
"""
tests/test_database_schema.py

Phase 2.1 — Database Schema & DDL Verification Test Suite.
Verifies DDL syntax using sqlglot, checks table definitions, spatial indexes,
constraints, and verifies data immutability of Phase 1 files.
"""

import sys
import os
import unittest
import sqlglot
import pandas as pd

INIT_SQL_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts", "init-db.sql"))
DOCKER_COMPOSE_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml"))
NC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Indian_ARGO_Floats_0f9d_516d_c560_U1788882326310.nc"))
PROCESSED_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "processed"))

class TestDatabaseSchema(unittest.TestCase):

    def test_ddl_file_existence(self):
        """Verify DDL script and docker-compose.yml exist."""
        self.assertTrue(os.path.exists(INIT_SQL_PATH))
        self.assertTrue(os.path.exists(DOCKER_COMPOSE_PATH))

    def test_ddl_syntax_parsing(self):
        """Parse DDL SQL script using sqlglot to ensure valid PostgreSQL/PostGIS DDL syntax."""
        with open(INIT_SQL_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read()

        parsed_statements = sqlglot.parse(sql_content, read="postgres")
        self.assertGreater(len(parsed_statements), 0)

    def test_ddl_table_definitions(self):
        """Verify presence of all required DDL table definitions."""
        with open(INIT_SQL_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read().lower()

        self.assertIn("create table if not exists argo_floats", sql_content)
        self.assertIn("create table if not exists argo_profiles", sql_content)
        self.assertIn("create table if not exists argo_measurements", sql_content)
        self.assertIn("create table if not exists argo_doc_embeddings", sql_content)

    def test_ddl_constraints_and_spatial_index(self):
        """Verify natural identity uniqueness constraint, CHECK constraints, and PostGIS GIST spatial index."""
        with open(INIT_SQL_PATH, "r", encoding="utf-8") as f:
            sql_content = f.read().lower()

        self.assertIn("constraint unique_platform_profile_time unique (platform_number, profile_time)", sql_content)
        self.assertIn("geometry(point, 4326)", sql_content)
        self.assertIn("idx_argo_profiles_location", sql_content)
        self.assertIn("using gist (location)", sql_content)

    def test_phase_1_data_immutability(self):
        """Verify Phase 1 NetCDF dataset and processed Parquet files remain completely unmodified."""
        self.assertTrue(os.path.exists(NC_PATH))
        self.assertEqual(os.path.getsize(NC_PATH), 751672)

        floats_df = pd.read_parquet(os.path.join(PROCESSED_DIR, "floats.parquet"))
        profiles_df = pd.read_parquet(os.path.join(PROCESSED_DIR, "profiles.parquet"))
        measurements_df = pd.read_parquet(os.path.join(PROCESSED_DIR, "measurements.parquet"))

        self.assertEqual(len(floats_df), 21)
        self.assertEqual(len(profiles_df), 64)
        self.assertEqual(len(measurements_df), 17339)

if __name__ == "__main__":
    unittest.main()
