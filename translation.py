import json
import os
import sys

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class Translator:
    def __init__(self, default_language_code='en'):
        self.language_data = {}
        self.fallback_data = {}
        self.current_lang_code = default_language_code
        
        self.available_languages = {
            'es': 'Español',
            'en': 'English',
            'pt': 'Português'
        }

        try:
            fallback_path = resource_path(os.path.join('lang', f'{default_language_code}.json'))
            with open(fallback_path, 'r', encoding='utf-8') as f:
                self.fallback_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ERROR: Fallback language file '{default_language_code}.json' could not be loaded: {e}")
            self.fallback_data = {}

        self.load_language(self.current_lang_code)

    def load_language(self, lang_code):
        if lang_code not in self.available_languages:
            print(f"WARNING: Language code '{lang_code}' not supported. Falling back to 'en'.")
            lang_code = 'en'

        try:
            file_path = resource_path(os.path.join('lang', f'{lang_code}.json'))
            with open(file_path, 'r', encoding='utf-8') as f:
                self.language_data = json.load(f)
            self.current_lang_code = lang_code
            print(f"Language loaded successfully: {lang_code}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"ERROR: Could not load language file for '{lang_code}'. Using fallback. Error: {e}")
            self.language_data = self.fallback_data
            self.current_lang_code = 'en'

    def get(self, key):
        keys = key.split('.')
        
        current_dict = self.language_data
        for k in keys:
            current_dict = current_dict.get(k, None)
            if current_dict is None:
                break
        
        if current_dict is not None:
            return current_dict

        current_dict = self.fallback_data
        for k in keys:
            current_dict = current_dict.get(k, None)
            if current_dict is None:
                break

        if current_dict is not None:
            return current_dict

        print(f"WARNING: Translation key not found in '{self.current_lang_code}' or fallback: '{key}'")
        return key

    def get_available_languages(self):
        return self.available_languages

    def get_current_language_code(self):
        return self.current_lang_code