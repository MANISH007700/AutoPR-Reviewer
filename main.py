import os

from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from dotenv import load_dotenv
from openai import OpenAI

# Load environment variables from .env file
load_dotenv()

# Initialize channel ID
channel_id = os.getenv("CHANNEL_ID", "")
if not channel_id:
    channel_id = input("Enter Slack Channel ID: ")

# Get OpenRouter API key
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
if not openrouter_api_key:
    openrouter_api_key = input("Enter your OpenRouter API key: ")
    if not openrouter_api_key:
        raise ValueError(
            "OpenRouter API key is required. Set OPENROUTER_API_KEY in .env or enter it when prompted."
        )

# Initialize OpenRouter client
try:
    openrouter_client = OpenAI(
        api_key=openrouter_api_key,
        base_url="https://openrouter.ai/api/v1",
    )
except Exception as e:
    raise ValueError(f"Failed to initialize OpenRouter client: {str(e)}")

# Define code review assistant prompt
code_review_assistant_prompt = (
    "You are an experienced code reviewer. Your task is to review the provided file diff and give constructive feedback.\n\n"
    "Follow these steps:\n"
    "1. Identify if the file contains significant logic changes.\n"
    "2. Summarize the changes in the diff in clear and concise English, within 100 words.\n"
    "3. Provide actionable suggestions if there are any issues in the code.\n\n"
    f"Once decided on changes, for any TODOs, create a Github issue. Send the PR review summary to {channel_id} channel on Slack "
    "(plain text, no markdown). Also add the comprehensive review as a PR comment."
)

# Initialize Composio tools
composio_toolset = ComposioToolSet()
pr_agent_tools = composio_toolset.get_tools(
    actions=[
        Action.GITHUB_GET_A_PULL_REQUEST,
        Action.GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST,
        Action.GITHUB_CREATE_AN_ISSUE,
        Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
    ]
)


# Function to create assistant with specified model
def create_assistant(model="google/gemma-3-12b-it:free"):
    try:
        assistant = openrouter_client.beta.assistants.create(
            name="PR Review Assistant",
            description="An assistant for reviewing pull requests",
            instructions=code_review_assistant_prompt,
            model=model,
            tools=pr_agent_tools,
        )
        return assistant
    except Exception as e:
        raise ValueError(f"Failed to create assistant: {str(e)}")


# Initialize assistant with Google Gemma 3 12B model
try:
    model = "google/gemma-3-12b-it:free"
    assistant = create_assistant(model=model)
    print(f"Assistant is ready with model: {model}")
except Exception as e:
    print(f"Error initializing assistant: {str(e)}")
    exit(1)

# Create trigger listener
listener = composio_toolset.create_trigger_listener()


# Handler for new PR events
@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    try:
        # Extract code diff from event payload
        code_to_review = str(event.payload)

        # Create thread and add message
        thread = openrouter_client.beta.threads.create()
        openrouter_client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=code_to_review,
        )

        # Log thread URL (may not be functional with OpenRouter)
        url = f"https://openrouter.ai/playground?assistant={assistant.id}&thread={thread.id}"
        print(f"Thread URL (if supported): {url}")

        # Run assistant
        run = openrouter_client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id,
        )

        # Handle tool calls
        composio_toolset.wait_and_handle_assistant_tool_calls(
            client=openrouter_client,
            run=run,
            thread=thread,
        )

    except Exception as e:
        print(f"Error reviewing PR: {str(e)}")


# Start the listener
print("Listener started!")
print("Create a PR to trigger a review")
try:
    listener.wait_forever()
except KeyboardInterrupt:
    print("Listener stopped by user")
