import anthropic

client = anthropic.Anthropic()

skills = client.beta.skills.list(
    limit=100,
    source="anthropic",
)

for skill in skills.data:
    print(f"{skill.id}: {skill.display_title}")