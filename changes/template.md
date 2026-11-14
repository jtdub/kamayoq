{% for section, _ in sections.items() %}
{% for category, val in definitions.items() if category in sections[section] %}

### {{ definitions[category]["name"] }}

{% for text, values in sections[section][category].items() %}
{% for line in text.splitlines() if line.strip() %}
- {{ line.strip() }}{% if values %} ({{ values | join(", ") }}){% endif %}

{% endfor %}
{% endfor %}
{% endfor %}
{% endfor %}
