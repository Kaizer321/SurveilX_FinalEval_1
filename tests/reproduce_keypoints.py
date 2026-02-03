
import unittest
from fastapi.testclient import TestClient
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from app import app, require_admin, require_any_role

# Mock auth
async def mock_require_admin():
    return "admin"

async def mock_require_any():
    return "user"

app.dependency_overrides[require_admin] = mock_require_admin
app.dependency_overrides[require_any_role] = mock_require_any

client = TestClient(app)

class TestKeypointToggle(unittest.TestCase):
    def test_toggle_true(self):
        # Frontend sends {"enabled": true}
        response = client.post("/api/detections/keypoints", json={"enabled": True})
        print(f"\nResponse (enabled=True): {response.status_code} {response.text}")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["show_keypoints"])

    def test_toggle_false(self):
        # Frontend sends {"enabled": false}
        response = client.post("/api/detections/keypoints", json={"enabled": False})
        print(f"\nResponse (enabled=False): {response.status_code} {response.text}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["show_keypoints"])
    
    def test_with_extra_field(self):
        # What if frontend sends extra fields?
        response = client.post("/api/detections/keypoints", json={"enabled": True, "extra": "foo"})
        print(f"\nResponse (extra fields): {response.status_code} {response.text}")
        # Dict[str, bool] means ALL values must be bool. "foo" is string. This MUST fail validation.
        # This confirms a fragility: if anything else is sent, it breaks.
        self.assertEqual(response.status_code, 200) 

if __name__ == "__main__":
    unittest.main()
