
import unittest
import sys
import os
import time

def run_suite():
    print("="*60)
    print("      VIOLENCE DETECTION SYSTEM - EVALUATION SUITE      ")
    print("="*60)
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Python: {sys.version.split()[0]}")
    print("-" * 60)

    loader = unittest.TestLoader()
    start_dir = os.path.join(os.path.dirname(__file__), 'tests')
    
    # Discover all tests in 'tests' directory
    suite = loader.discover(start_dir, pattern='test_*.py')
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("="*60)
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED SUCCESSFULLY")
        print(f"Total Tests Run: {result.testsRun}")
    else:
        print("❌ SOME TESTS FAILED")
        print(f"Failures: {len(result.failures)}")
        print(f"Errors: {len(result.errors)}")
    print("="*60)
    
    if result.wasSuccessful():
        exit(0)
    else:
        exit(1)

if __name__ == "__main__":
    run_suite()
