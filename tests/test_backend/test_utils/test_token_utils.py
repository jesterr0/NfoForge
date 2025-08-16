from src.backend.utils.token_utils import get_prompt_tokens


class TestGetPromptTokens:
    def test_basic_variable_output(self):
        template = "{{ prompt_username }} and {{ prompt_email }}"
        tokens = get_prompt_tokens(template)
        assert tokens == ("prompt_username", "prompt_email")

    def test_conditional_blocks(self):
        template = """
        {% if prompt_admin %}
            Admin content
        {% endif %}
        {% if not prompt_guest %}
            Member content
        {% endif %}
        """
        tokens = get_prompt_tokens(template)
        assert "prompt_admin" in tokens
        assert "prompt_guest" in tokens

    def test_function_calls(self):
        template = "{{ len(prompt_data) }} {{ format_text(prompt_message) }}"
        tokens = get_prompt_tokens(template)
        assert "prompt_data" in tokens
        assert "prompt_message" in tokens

    def test_filters(self):
        template = "{{ prompt_content|safe }} {{ prompt_date|strftime('%Y-%m-%d') }}"
        tokens = get_prompt_tokens(template)
        assert "prompt_content" in tokens
        assert "prompt_date" in tokens

    def test_no_duplicates(self):
        template = (
            "{{ prompt_user }} {% if prompt_user %} {{ prompt_user }} {% endif %}"
        )
        tokens = get_prompt_tokens(template)
        assert tokens.count("prompt_user") == 1

    def test_comments_ignored(self):
        template = "{# This is a comment with prompt_fake #} {{ prompt_real }}"
        tokens = get_prompt_tokens(template)
        assert "prompt_fake" not in tokens
        assert "prompt_real" in tokens

    def test_edge_cases(self):
        template = """
        {{prompt_no_spaces}}
        {%   if   prompt_with_spaces   %}
        {{ some_func( prompt_in_parens ) }}
        """
        tokens = get_prompt_tokens(template)
        assert "prompt_no_spaces" in tokens
        assert "prompt_with_spaces" in tokens
        assert "prompt_in_parens" in tokens
