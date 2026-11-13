import logging
import json
import secrets
from datetime import timedelta
from django.conf import settings
from django.core.mail import send_mail
from django.contrib.auth.forms import SetPasswordForm
from django.utils import timezone
from . import otp as otp_service
from django.shortcuts import render
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.contrib import messages
from .forms import MobileResetForm
from .models import PasswordResetOTP, CustomUser
from django.shortcuts import render, redirect
from .forms import SignUpForm, ProfileUpdateForm
from django.contrib.auth.decorators import login_required
from .forms import ProfileUpdateForm
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt 
from django.views.decorators.http import require_POST
from .nlp_utils import extract_preferences_from_text


logger = logging.getLogger(__name__)

def sign_up(request):
    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            # The post_save signal in users/models.py already created the profile.
            profile = user.profile
            profile.mobile_number = form.cleaned_data['mobile_number']
            profile.save(update_fields=['mobile_number'])
            return redirect('login')  # Redirect to login after sign up
    else:
        form = SignUpForm()
    return render(request, 'registration/sign_up.html', {"form": form})

def password_reset_mobile(request):
    if request.method == "POST":
        mobile = (request.POST.get('mobile') or '').strip()
        user = CustomUser.objects.filter(mobile_number=mobile).first()
        if not user:
            messages.error(request, "No account is registered with this mobile number.")
            return render(request, 'registration/password_reset_mobile.html', {'mobile': mobile})

        latest = PasswordResetOTP.objects.filter(user=user).order_by('-created_at').first()
        if latest and timezone.now() < latest.created_at + timedelta(seconds=otp_service.RESEND_COOLDOWN_SECONDS):
            wait = int((latest.created_at + timedelta(seconds=otp_service.RESEND_COOLDOWN_SECONDS) - timezone.now()).total_seconds()) + 1
            messages.warning(request, f"Please wait {wait} seconds before requesting a new code.")
            request.session['reset_mobile_user'] = user.id
            return redirect('password_reset_mobile_verify')

        # Only the newest code is ever valid.
        PasswordResetOTP.objects.filter(user=user).delete()
        otp = otp_service.generate_otp()
        PasswordResetOTP.objects.create(user=user, otp=otp)
        reached = otp_service.deliver_otp(user, mobile, otp)

        request.session['reset_mobile_user'] = user.id
        if reached:
            messages.success(request, "Verification code sent by " + " and ".join(reached) + ".")
        elif settings.DEBUG:
            messages.warning(request, "No SMS/email channel is configured. In development the code is printed in the server terminal.")
        else:
            messages.error(request, "We couldn't send a verification code right now. Please try again later.")
            return render(request, 'registration/password_reset_mobile.html', {'mobile': mobile})
        return redirect('password_reset_mobile_verify')
    return render(request, 'registration/password_reset_mobile.html')


def password_reset_mobile_verify(request):
    user_id = request.session.get('reset_mobile_user')
    user = CustomUser.objects.filter(id=user_id).first() if user_id else None
    if not user:
        messages.error(request, "Session expired. Please request a new code.")
        return redirect('password_reset_mobile')

    if request.method == "POST":
        entered = (request.POST.get('otp') or '').strip()
        otp_obj = PasswordResetOTP.objects.filter(user=user).order_by('-created_at').first()
        if not otp_obj or not otp_obj.is_valid():
            messages.error(request, "This code has expired. Please request a new one.")
            return redirect('password_reset_mobile')
        if otp_obj.attempts >= otp_service.MAX_VERIFY_ATTEMPTS:
            otp_obj.delete()
            messages.error(request, "Too many incorrect attempts. Please request a new code.")
            return redirect('password_reset_mobile')
        if secrets.compare_digest(entered, otp_obj.otp):
            otp_obj.delete()
            del request.session['reset_mobile_user']
            request.session['otp_verified_user_id'] = user.id
            return redirect('password_reset_mobile_set_new_password')
        otp_obj.attempts += 1
        otp_obj.save(update_fields=['attempts'])
        remaining = otp_service.MAX_VERIFY_ATTEMPTS - otp_obj.attempts
        messages.error(request, f"Incorrect code. {remaining} attempt(s) left.")

    return render(request, 'registration/password_reset_mobile_verify.html', {
        'masked_mobile': otp_service.mask_mobile(user.mobile_number),
    })


def password_reset_mobile_set_new_password(request):
    user_id = request.session.get('otp_verified_user_id')
    user = CustomUser.objects.filter(id=user_id).first() if user_id else None
    if not user:
        messages.error(request, "Session expired or unauthorized access.")
        return redirect('password_reset_mobile')

    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        del request.session['otp_verified_user_id']
        messages.success(request, f"Password reset successful. Log in with your username: {user.get_username()}")
        return redirect('login')
    return render(request, 'registration/password_reset_mobile_set_new_password.html', {'form': form})


def forgot_username(request):
    """Email the username(s) registered to an address. Same response either way to avoid account enumeration."""
    if request.method == "POST":
        email = (request.POST.get('email') or '').strip()
        users = list(CustomUser.objects.filter(email__iexact=email, is_active=True)) if email else []
        if users and otp_service.email_is_configured():
            names = "\n".join(f"  - {u.get_username()}" for u in users)
            try:
                send_mail(
                    subject='Your SmartShop username',
                    message=(
                        "You asked us to remind you of your SmartShop username.\n\n"
                        f"Username(s) registered with this email:\n{names}\n\n"
                        "If you didn't request this, you can ignore this email."
                    ),
                    from_email=settings.EMAIL_HOST_USER,
                    recipient_list=[users[0].email],
                )
            except Exception as exc:
                logger.warning("Username reminder email failed: %s", exc)
        elif users and settings.DEBUG:
            logger.warning("[DEV] Username reminder for %s: %s", email, [u.get_username() for u in users])
        messages.success(request, "If an account exists for that email, we've sent the username to it.")
        return redirect('login')
    return render(request, 'registration/forgot_username.html')


def password_reset_options(request):
    return render(request, 'registration/password_reset_options.html')

@login_required
def edit_profile(request):
    if request.method == "POST":
        form = ProfileUpdateForm(request.POST, instance=request.user.profile)
        if form.is_valid():
            form.save()
            print(form.cleaned_data)
            return redirect('profile')
    else:
        form = ProfileUpdateForm(instance=request.user.profile)
    return render(request, 'registration/edit_profile.html', {'form': form})

@login_required
def profile(request):
    if request.method == 'POST':
        # Handle form submission for updating the profile
        p_form = ProfileUpdateForm(request.POST, request.FILES, instance=request.user.profile)
        if p_form.is_valid():
            p_form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('dashboard')  # Redirect back to the profile page
    else:
        # Display the profile form with pre-filled data
        p_form = ProfileUpdateForm(instance=request.user.profile)

    context = {
        'p_form': p_form,
        'title': 'Your Profile'
    }
    return render(request, 'registration/profile.html', context)


        
@csrf_exempt
@login_required
def process_preference_input(request):
    """API endpoint to process text/voice input and return extracted data."""
    import json
    from .nlp_utils import extract_preferences_from_text

    try:
        body = json.loads(request.body)
        text_input = body.get('text', '')
        if not text_input:
            return JsonResponse({'status': 'error', 'message': 'No text provided'}, status=400)

        # Extract preferences using NLP utility
        extracted_data = extract_preferences_from_text(text_input)

        # Return the actual extracted data!
        return JsonResponse({'status': 'success', 'data': extracted_data})

    except json.JSONDecodeError:
        return JsonResponse({'status': 'error', 'message': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'An error occurred: {str(e)}'}, status=500)
