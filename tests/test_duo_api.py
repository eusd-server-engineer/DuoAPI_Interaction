"""
Unit tests for Duo API client
"""

import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.duo_student_cleanup import DuoAdminAPI, is_student_account, is_directory_managed


class TestDuoAdminAPI(unittest.TestCase):
    """Test cases for DuoAdminAPI class"""

    def setUp(self):
        """Set up test fixtures"""
        self.api = DuoAdminAPI(
            integration_key="test_ikey",
            secret_key="test_skey",
            api_host="api-test.duosecurity.com"
        )

    def test_initialization(self):
        """Test API client initialization"""
        self.assertEqual(self.api.ikey, "test_ikey")
        self.assertEqual(self.api.skey, "test_skey")
        self.assertEqual(self.api.host, "api-test.duosecurity.com")
        self.assertEqual(self.api.base_url, "https://api-test.duosecurity.com")

    @patch('scripts.duo_student_cleanup.requests.request')
    def test_get_user_by_username_found(self, mock_request):
        """Test getting user by username when user exists"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'stat': 'OK',
            'response': [{
                'user_id': 'test_user_id',
                'username': '123456'
            }]
        }
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        user = self.api.get_user_by_username('123456')

        self.assertIsNotNone(user)
        self.assertEqual(user['username'], '123456')
        self.assertEqual(user['user_id'], 'test_user_id')

    @patch('scripts.duo_student_cleanup.requests.request')
    def test_get_user_by_username_not_found(self, mock_request):
        """Test getting user by username when user doesn't exist"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'stat': 'OK',
            'response': []
        }
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        user = self.api.get_user_by_username('nonexistent')

        self.assertIsNone(user)

    @patch('scripts.duo_student_cleanup.requests.request')
    def test_delete_user_success(self, mock_request):
        """Test successful user deletion"""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            'stat': 'OK',
            'response': {}
        }
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.api.delete_user('test_user_id')

        self.assertTrue(result)

    @patch('scripts.duo_student_cleanup.requests.request')
    def test_delete_user_failure(self, mock_request):
        """Test failed user deletion"""
        mock_request.side_effect = Exception("API Error")

        result = self.api.delete_user('test_user_id')

        self.assertFalse(result)


class TestHelperFunctions(unittest.TestCase):
    """Test cases for helper functions"""

    def test_is_student_account_valid(self):
        """Test student account pattern matching for valid accounts"""
        self.assertTrue(is_student_account('123456'))
        self.assertTrue(is_student_account('000000'))
        self.assertTrue(is_student_account('999999'))
        self.assertTrue(is_student_account('123456@eusd.org'))

    def test_is_student_account_invalid(self):
        """Test student account pattern matching for invalid accounts"""
        self.assertFalse(is_student_account('12345'))  # Too short
        self.assertFalse(is_student_account('1234567'))  # Too long
        self.assertFalse(is_student_account('abc123'))  # Contains letters
        self.assertFalse(is_student_account('john.doe'))  # Staff pattern
        self.assertFalse(is_student_account(''))  # Empty

    def test_is_directory_managed_true(self):
        """Test detection of directory-managed users"""
        user_with_directory_key = {'directory_key': 'some_key'}
        user_with_external_id = {'external_id': 'ext_123'}
        user_with_last_sync = {'last_directory_sync': '2024-01-01'}

        self.assertTrue(is_directory_managed(user_with_directory_key))
        self.assertTrue(is_directory_managed(user_with_external_id))
        self.assertTrue(is_directory_managed(user_with_last_sync))

    def test_is_directory_managed_false(self):
        """Test detection of non-directory-managed users"""
        unmanaged_user = {
            'username': '123456',
            'user_id': 'test_id'
        }
        self.assertFalse(is_directory_managed(unmanaged_user))

        empty_user = {}
        self.assertFalse(is_directory_managed(empty_user))


if __name__ == '__main__':
    unittest.main()