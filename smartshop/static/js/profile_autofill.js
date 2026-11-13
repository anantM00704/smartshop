document.addEventListener('DOMContentLoaded', () => {
    const preferenceInput = document.getElementById('preference-input');
    const processTextBtn = document.getElementById('process-text-btn');
    const voiceInputBtn = document.getElementById('voice-input-btn');
    const voiceStatus = document.getElementById('voice-status');

    const processApiUrl = '/users/api/process-preferences/';

    // Helper function to get CSRF token from cookies
    function getCSRFToken() {
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrftoken') {
                return value;
            }
        }
        return null;
    } // Ensure this matches your Django URL configuration

    const feedback = document.getElementById('preference-feedback');

    function showFeedback(kind, html) {
        if (!feedback) return;
        feedback.className = `alert alert-${kind} py-2 small mt-2 mb-0`;
        feedback.innerHTML = html;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // --- Helper Function to Update Form ---
    const FIELDS = {
        preferred_department: { id: 'id_preferred_department', label: 'Department' },
        height_cm: { id: 'id_height_cm', label: 'Height', suffix: ' cm' },
        weight_kg: { id: 'id_weight_kg', label: 'Weight', suffix: ' kg' },
        age_group: { id: 'id_age_group', label: 'Age group' },
        preferred_fit: { id: 'id_preferred_fit', label: 'Fit' },
    };

    function setFieldValue(element, value) {
        // A <select> silently ignores values that aren't one of its options, so check first.
        if (element.tagName === 'SELECT' &&
            !Array.from(element.options).some(opt => opt.value === String(value))) {
            return false;
        }
        element.value = value;
        element.dispatchEvent(new Event('change', { bubbles: true }));
        element.classList.add('is-valid');
        setTimeout(() => element.classList.remove('is-valid'), 3000);
        return true;
    }

    function updateFormFields(data, sourceText) {
        const filled = [];
        for (const [key, field] of Object.entries(FIELDS)) {
            if (data[key] === undefined || data[key] === null) continue;
            const element = document.getElementById(field.id);
            if (element && setFieldValue(element, data[key])) {
                filled.push(`<strong>${field.label}:</strong> ${escapeHtml(String(data[key]))}${field.suffix || ''}`);
            }
        }
        if (filled.length) {
            showFeedback('success',
                `Filled ${filled.length} field${filled.length > 1 ? 's' : ''}: ${filled.join(' &middot; ')}. ` +
                'Review them and click <strong>Save Profile</strong>.');
        } else {
            showFeedback('warning',
                `Couldn't find profile details in “${escapeHtml(sourceText)}”. ` +
                'Try something like “I am a man, 5 feet 8 inches, 70 kg, 25 years old, slim fit”.');
        }
    }

    // --- API Call Function ---
    async function sendDataToApi(text) {
        try {
            const response = await fetch(processApiUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken(),
                },
                body: JSON.stringify({ text: text })
            });

            const result = await response.json().catch(() => ({}));
            if (!response.ok || result.status !== 'success') {
                throw new Error(result.message || `Server error (${response.status})`);
            }
            updateFormFields(result.data || {}, text);
        } catch (error) {
            console.error('Preference processing failed:', error);
            showFeedback('danger', `Couldn't process your input: ${escapeHtml(error.message)}`);
        } finally {
            voiceStatus.textContent = '';
        }
    }

    // --- Event Listener for Text Button ---
    processTextBtn.addEventListener('click', () => {
        const text = preferenceInput.value.trim();
        if (text) {
            voiceStatus.textContent = 'Processing text...';
            sendDataToApi(text);
        } else {
            showFeedback('warning', 'Type or speak your preferences first.');
        }
    });

    // --- Event Listener and Logic for Voice Button ---
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.continuous = false;
        recognition.lang = 'en-US';
        recognition.interimResults = false;

        voiceInputBtn.addEventListener('click', () => {
            voiceStatus.textContent = 'Listening...';
            voiceInputBtn.disabled = true;
            recognition.start();
        });

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            preferenceInput.value = transcript;
            voiceStatus.textContent = 'Processing voice input...';
            sendDataToApi(transcript);
        };

        recognition.onspeechend = () => {
            recognition.stop();
            voiceStatus.textContent = 'Finished listening.';
            voiceInputBtn.disabled = false;
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error:', event.error);
            voiceStatus.textContent = `Error: ${event.error}`;
            voiceInputBtn.disabled = false;
        };

        recognition.onnomatch = () => {
            voiceStatus.textContent = "Didn't recognize that. Please try again.";
            voiceInputBtn.disabled = false;
        };
    } else {
        voiceInputBtn.disabled = true;
        voiceStatus.textContent = 'Voice recognition not supported by your browser.';
    }
});
