#!/usr/bin/env python3
"""
tests/test_sql_validator.py

Phase 3.1 — Deterministic SQL Validator Test Suite.
Contains 35+ automated test cases verifying SQL security AST parsing, table/column allowlisting,
PostGIS spatial function checks, single-statement enforcement, LIMIT policy, and injection containment.
"""

import sys
import os
import unittest

# Add src to python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.security.sql_validator import (
    DeterministicSQLValidator,
    ValidationErrorCode,
    SQLValidationResult,
)

class TestSQLValidator(unittest.TestCase):

    def setUp(self):
        self.validator = DeterministicSQLValidator()

    # ===================================================================
    # Category A: Basic Valid Queries
    # ===================================================================

    def test_01_simple_select(self):
        sql = "SELECT platform_number FROM argo_floats"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)
        self.assertIn("LIMIT 500", res.normalized_sql)

    def test_02_select_with_where(self):
        sql = "SELECT profile_id, latitude, longitude FROM argo_profiles WHERE latitude > 10.0"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_03_select_with_existing_limit(self):
        sql = "SELECT platform_number FROM argo_floats LIMIT 50"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)
        self.assertIn("LIMIT 50", res.normalized_sql)

    def test_04_select_with_order_by(self):
        sql = "SELECT profile_id, profile_time FROM argo_profiles ORDER BY profile_time DESC"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_05_select_with_aggregation(self):
        sql = "SELECT COUNT(*), AVG(temperature_c), MIN(pressure_dbar), MAX(salinity_psu) FROM argo_measurements"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_06_group_by_having(self):
        sql = "SELECT profile_id, AVG(temperature_c) FROM argo_measurements GROUP BY profile_id HAVING AVG(temperature_c) > 20.0"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_07_inner_join(self):
        sql = """
            SELECT p.platform_number, p.profile_time, m.pressure_dbar, m.temperature_c
            FROM argo_profiles p
            JOIN argo_measurements m ON p.profile_id = m.profile_id
            WHERE m.pressure_dbar BETWEEN 0 AND 500
        """
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    # ===================================================================
    # Category B: Valid FloatChat Domain & PostGIS Queries
    # ===================================================================

    def test_08_floatchat_profile_query(self):
        sql = "SELECT profile_id, platform_number, profile_time FROM argo_profiles WHERE platform_number = '1902671'"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_09_floatchat_measurement_query(self):
        sql = "SELECT pressure_dbar, temperature_c, salinity_psu FROM argo_measurements WHERE pressure_dbar <= 200.0"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_10_temperature_filtering(self):
        sql = "SELECT profile_id, temperature_c FROM argo_measurements WHERE temperature_c > 28.0"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_11_salinity_filtering(self):
        sql = "SELECT profile_id, salinity_psu FROM argo_measurements WHERE salinity_psu < 30.0"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_12_temporal_filtering(self):
        sql = "SELECT profile_id, profile_time FROM argo_profiles WHERE profile_time >= '2024-01-01T00:00:00Z'"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_13_postgis_bounding_box_query(self):
        sql = """
            SELECT profile_id, latitude, longitude 
            FROM argo_profiles 
            WHERE ST_Within(location, ST_MakeEnvelope(60.0, -10.0, 80.0, 10.0, 4326))
        """
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_14_postgis_radial_distance_query(self):
        sql = """
            SELECT profile_id, ST_Distance(location, ST_SetSRID(ST_MakePoint(75.0, 0.0), 4326)) AS dist
            FROM argo_profiles 
            WHERE ST_DWithin(location, ST_SetSRID(ST_MakePoint(75.0, 0.0), 4326), 500000)
        """
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    def test_15_valid_cte_query(self):
        sql = """
            WITH profile_summary AS (
                SELECT profile_id, platform_number FROM argo_profiles WHERE latitude > 15.0
            )
            SELECT p.profile_id, p.platform_number FROM profile_summary p
        """
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)

    # ===================================================================
    # Category C: Rejections & Security Boundary Tests
    # ===================================================================

    def test_16_reject_empty_sql(self):
        res = self.validator.validate("")
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.EMPTY_SQL)

    def test_17_reject_whitespace_sql(self):
        res = self.validator.validate("   \n \t ")
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.EMPTY_SQL)

    def test_18_reject_malformed_sql(self):
        res = self.validator.validate("SELECT FROM WHERE WHERE")
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.PARSE_ERROR)

    def test_19_reject_multiple_statements(self):
        sql = "SELECT platform_number FROM argo_floats; DROP TABLE argo_profiles;"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.MULTIPLE_STATEMENTS)

    def test_20_reject_insert(self):
        sql = "INSERT INTO argo_floats (platform_number) VALUES ('9999999')"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_21_reject_update(self):
        sql = "UPDATE argo_measurements SET temperature_c = 0.0"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_22_reject_delete(self):
        sql = "DELETE FROM argo_profiles WHERE profile_id = 'PROF_1'"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_23_reject_drop(self):
        sql = "DROP TABLE argo_measurements"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_24_reject_alter(self):
        sql = "ALTER TABLE argo_floats ADD COLUMN secret TEXT"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_25_reject_truncate(self):
        sql = "TRUNCATE argo_measurements"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.NON_SELECT_STATEMENT)

    def test_26_reject_unauthorized_table(self):
        sql = "SELECT * FROM users"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNAUTHORIZED_TABLE)

    def test_27_reject_information_schema(self):
        sql = "SELECT table_name FROM information_schema.tables"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertIn(res.error_code, (ValidationErrorCode.UNAUTHORIZED_TABLE, ValidationErrorCode.UNSAFE_CONSTRUCT))

    def test_28_reject_pg_catalog(self):
        sql = "SELECT tablename FROM pg_catalog.pg_tables"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertIn(res.error_code, (ValidationErrorCode.UNAUTHORIZED_TABLE, ValidationErrorCode.UNSAFE_CONSTRUCT))

    def test_29_reject_unauthorized_column(self):
        sql = "SELECT password FROM argo_profiles"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNAUTHORIZED_COLUMN)

    def test_30_reject_nonexistent_column(self):
        sql = "SELECT depth FROM argo_measurements"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNAUTHORIZED_COLUMN)

    def test_31_reject_select_into(self):
        sql = "SELECT platform_number INTO new_floats FROM argo_floats"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNSAFE_CONSTRUCT)

    def test_32_reject_unsafe_system_function(self):
        sql = "SELECT pg_read_file('/etc/passwd') FROM argo_floats"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNSAFE_FUNCTION)

    def test_33_reject_nested_unauthorized_table_in_subquery(self):
        sql = "SELECT profile_id FROM argo_profiles WHERE platform_number IN (SELECT id FROM admin_users)"
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNAUTHORIZED_TABLE)

    def test_34_reject_unauthorized_table_in_cte(self):
        sql = """
            WITH bad_cte AS (
                SELECT user_id FROM secret_credentials
            )
            SELECT profile_id FROM argo_profiles
        """
        res = self.validator.validate(sql)
        self.assertFalse(res.valid)
        self.assertEqual(res.error_code, ValidationErrorCode.UNAUTHORIZED_TABLE)

    # ===================================================================
    # Category D: LIMIT Policy Tests
    # ===================================================================

    def test_35_limit_auto_injection(self):
        sql = "SELECT platform_number FROM argo_floats"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)
        self.assertIn("LIMIT 500", res.normalized_sql)
        self.assertTrue(len(res.warnings) > 0)

    def test_36_limit_excessive_capping(self):
        sql = "SELECT platform_number FROM argo_floats LIMIT 5000"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)
        self.assertIn("LIMIT 1000", res.normalized_sql)
        self.assertTrue(len(res.warnings) > 0)

    def test_37_limit_preserves_valid_limit(self):
        sql = "SELECT platform_number FROM argo_floats LIMIT 100"
        res = self.validator.validate(sql)
        self.assertTrue(res.valid)
        self.assertIn("LIMIT 100", res.normalized_sql)
        self.assertEqual(len(res.warnings), 0)

if __name__ == "__main__":
    unittest.main()
