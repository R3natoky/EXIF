import unittest
import sys
import os

# Adjust the path to import from the parent directory (project root)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from core.geo import dms_to_decimal, convert_to_utm
import config

class TestGeoFunctions(unittest.TestCase):

    def test_dms_to_decimal_north_east(self):
        self.assertAlmostEqual(dms_to_decimal(10, 30, 0, 'N'), 10.5)
        self.assertAlmostEqual(dms_to_decimal(75, 45, 0, 'E'), 75.75)

    def test_dms_to_decimal_south_west(self):
        self.assertAlmostEqual(dms_to_decimal(10, 30, 0, 'S'), -10.5)
        self.assertAlmostEqual(dms_to_decimal(75, 45, 0, 'W'), -75.75)

    def test_dms_to_decimal_zero_values(self):
        self.assertAlmostEqual(dms_to_decimal(0, 0, 0, 'N'), 0.0)
        self.assertAlmostEqual(dms_to_decimal(0, 0, 0, 'E'), 0.0)

    def test_dms_to_decimal_invalid_direction(self):
        with self.assertRaises(ValueError):
            dms_to_decimal(10, 30, 0, 'X')

    # For convert_to_utm, results depend on pyproj and its underlying PROJ data.
    # Exact easting/northing can vary slightly. We'll check zone, hemisphere, and approximate values.

    def test_convert_to_utm_known_point_hemisphere_n(self):
        # New York City: Lat 40.7128, Lon -74.0060
        # Expected: Zone 18N
        # Approximate expected values might vary, so we check for reasonable output.
        # Using an online converter: Easting ~583900, Northing ~4507200 for EPSG:32618
        # Temporarily disable debug mode for cleaner test output if pyproj prints errors
        original_debug_mode = config.DEBUG_MODE
        config.DEBUG_MODE = False
        easting, northing, zone, hemisphere = convert_to_utm(40.7128, -74.0060)
        config.DEBUG_MODE = original_debug_mode

        self.assertIsNotNone(easting, "Easting should not be None")
        self.assertIsNotNone(northing, "Northing should not be None")
        self.assertEqual(zone, 18, "Zone should be 18")
        self.assertEqual(hemisphere, 'N', "Hemisphere should be N")
        if easting is not None and northing is not None: 
            self.assertGreaterEqual(easting, 583000, "Easting approx check failed")
            self.assertLessEqual(easting, 585000, "Easting approx check failed")
            self.assertGreaterEqual(northing, 4506000, "Northing approx check failed")
            self.assertLessEqual(northing, 4508000, "Northing approx check failed")


    def test_convert_to_utm_known_point_hemisphere_s(self):
        # Sydney, Australia: Lat -33.8688, Lon 151.2093
        # Expected: Zone 56H (UTM uses H for S hemisphere in some letter schemes, but our func returns 'S')
        # Using an online converter: Easting ~333700, Northing ~6250000 for EPSG:32756
        original_debug_mode = config.DEBUG_MODE
        config.DEBUG_MODE = False
        easting, northing, zone, hemisphere = convert_to_utm(-33.8688, 151.2093)
        config.DEBUG_MODE = original_debug_mode
        
        self.assertIsNotNone(easting)
        self.assertIsNotNone(northing)
        self.assertEqual(zone, 56)
        self.assertEqual(hemisphere, 'S')
        if easting is not None and northing is not None:
            self.assertGreaterEqual(easting, 333000)
            self.assertLessEqual(easting, 335000)
            self.assertGreaterEqual(northing, 6249000)
            self.assertLessEqual(northing, 6251000)


    def test_convert_to_utm_invalid_lat_long(self):
        original_debug_mode = config.DEBUG_MODE
        config.DEBUG_MODE = False
        # Test with latitude > 90
        result_lat = convert_to_utm(95.0, 0.0)
        self.assertEqual(result_lat, (None, None, None, None))

        # Test with longitude > 180
        result_lon = convert_to_utm(0.0, 185.0)
        config.DEBUG_MODE = original_debug_mode
        self.assertEqual(result_lon, (None, None, None, None))

if __name__ == '__main__':
    unittest.main()
