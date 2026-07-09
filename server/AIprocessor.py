from openai import OpenAI
client = OpenAI()
models = client.models.list()

for m in sorted(models.data, key=lambda x: x.id):
    print(m.id)

response = client.responses.create(
    model="gpt-5.4-mini",
    input="Write a short bedtime story about a unicorn."
)

print(response.output_text)
