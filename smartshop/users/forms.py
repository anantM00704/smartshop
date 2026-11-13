from django import forms
from django.contrib.auth.forms import UserCreationForm
from .models import Address, CustomUser, Profile

class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)
    mobile_number = forms.CharField(max_length=15, required=True)

    class Meta:
        model = CustomUser
        fields = ('username', 'email', 'mobile_number', 'password1', 'password2')

class MobileResetForm(forms.Form):
    mobile_number = forms.CharField(max_length=15)
    otp = forms.CharField(max_length=6, required=False)
    new_password1 = forms.CharField(widget=forms.PasswordInput, required=False)
    new_password2 = forms.CharField(widget=forms.PasswordInput, required=False)

class ProfileUpdateForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = [
            'preferred_department', 'height_cm', 'weight_kg',
            'age_group', 'preferred_fit', 'mobile_number'
        ]  # delivery addresses are managed as saved Addresses


class AddressForm(forms.ModelForm):
    class Meta:
        model = Address
        fields = ['label', 'full_name', 'phone', 'line1', 'line2', 'city', 'state', 'pincode', 'is_default']
        widgets = {
            'phone': forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'tel'}),
            'pincode': forms.TextInput(attrs={'inputmode': 'numeric', 'maxlength': 6, 'autocomplete': 'postal-code'}),
            'line1': forms.TextInput(attrs={'autocomplete': 'address-line1'}),
            'line2': forms.TextInput(attrs={'autocomplete': 'address-line2'}),
            'city': forms.TextInput(attrs={'autocomplete': 'address-level2'}),
            'state': forms.TextInput(attrs={'autocomplete': 'address-level1'}),
            'full_name': forms.TextInput(attrs={'autocomplete': 'name'}),
        }

    def clean_phone(self):
        return ''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch == '+')