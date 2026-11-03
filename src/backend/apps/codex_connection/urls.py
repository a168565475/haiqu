from django.urls import path

from .views import CancelView, ChallengeView, ConnectionView, ModelView, OperationView


urlpatterns = [
    path('', ConnectionView.as_view(), name='codex-connection'),
    path('login-cancel/', CancelView.as_view(), name='codex-login-cancel'),
    path('challenge/', ChallengeView.as_view(), name='codex-challenge'),
    path('model/', ModelView.as_view(), name='codex-model'),
    *[path(action + '/', OperationView.as_view(action=action), name='codex-' + action)
      for action in ('login', 'switch', 'disconnect', 'refresh', 'test')],
]
