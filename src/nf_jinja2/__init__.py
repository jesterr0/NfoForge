from jinja2 import Environment, Template, FileSystemLoader


class Jinja2TemplateEngine:
    __slots__ = ("environment", "_added_globals")

    def __init__(self, template_dir: str | None = None, **env_options) -> None:
        """
        Initialize the Jinja2 template engine.

        :param template_dir: Directory containing templates (optional).
        :param env_options: Options to configure the Jinja2 Environment.
        """
        self._added_globals = []
        self.environment = Environment(
            loader=FileSystemLoader(template_dir) if template_dir else None,
            **env_options,
        )

    def add_global(self, name: str, value) -> None:
        """Add a global variable to the environment."""
        self.environment.globals[name] = value
        self._added_globals.append(name)

    def reset_added_globals(self) -> None:
        for item in self._added_globals:
            self.environment.globals.pop(item, None)
        self._added_globals.clear()

    def add_filter(self, name: str, func) -> None:
        """Add a custom filter to the environment."""
        self.environment.filters[name] = func

    def render_from_str(self, data: str, context: dict) -> str:
        """
        Render a template from string.

        :param data: Template in a string form.
        :param context: Context dictionary to render the template.
        """
        template = self.environment.from_string(data)
        return template.render(context)

    def render_from_env(self, template_name: str, context: dict) -> str:
        """
        Render a template from the Environment.

        :param template_name: Name of the template (from template_dir).
        :param context: Context dictionary to render the template.
        :return: Rendered template as a string.
        """
        template = self.environment.get_template(template_name)
        return template.render(context)

    def render_custom_template(
        self, template_str: str, context: dict, **custom_options
    ) -> str:
        """
        Render a one-off custom template with specific settings.

        :param template_str: Template string to render.
        :param context: Context dictionary to render the template.
        :param custom_options: Jinja2 template options (e.g., trim_blocks, lstrip_blocks).
        :return: Rendered template as a string.
        """
        custom_template = Template(template_str, **custom_options)
        return custom_template.render(context)
