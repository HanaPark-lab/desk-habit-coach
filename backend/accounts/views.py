from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render


def signup(request):
    """Django 기본 User로 회원가입. 중복 아이디·비밀번호 규칙은 UserCreationForm이 검사."""
    if request.user.is_authenticated:
        return redirect("today")
    form = UserCreationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        login(request, form.save())
        return redirect("today")
    return render(request, "accounts/signup.html", {"form": form})
