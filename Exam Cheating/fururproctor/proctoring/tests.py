from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import CheatingEvent, Exam, Student
from .views import TAB_SWITCH_LIMIT


class ExamTabSwitchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='student@example.com',
            email='student@example.com',
            password='password',
        )
        self.student = Student.objects.create(
            user=self.user,
            name='Test Student',
            email='student@example.com',
            photo=SimpleUploadedFile(
                'student.jpg',
                b'test-image',
                content_type='image/jpeg',
            ),
        )
        self.client.force_login(self.user)

    def test_record_tab_switch_auto_submits_at_limit(self):
        response = self.client.post(reverse('record_tab_switch'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], TAB_SWITCH_LIMIT)
        self.assertTrue(response.json()['auto_submit'])
        self.assertEqual(response.json()['status'], 'terminated')

        event = CheatingEvent.objects.get(student=self.student, event_type='tab_switch')
        self.assertEqual(event.tab_switch_count, TAB_SWITCH_LIMIT)
        self.assertTrue(event.cheating_flag)

    def test_forced_exam_submit_creates_exam_even_without_answers(self):
        response = self.client.post(reverse('submit_exam'), follow=True)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Exam.objects.filter(student=self.student).exists())
