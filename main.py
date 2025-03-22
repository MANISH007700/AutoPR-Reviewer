import os

from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from openai import OpenAI  # We'll use this as a compatible client for OpenRouter

# Initialize environment variables and channel ID
channel_id = os.getenv("CHANNEL_ID", "")
if not channel_id:
    channel_id = input("Enter Channel ID: ")

# Initialize OpenRouter client (using OpenAI client with OpenRouter base URL and API key)
openrouter_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),  # Set your OpenRouter API key in env
    base_url="https://openrouter.ai/api/v1",
)

# Code review assistant prompt
code_review_assistant_prompt = (
    """
    You are an experienced code reviewer.
    Your task is to review the provided file diff and give constructive feedback.

    Follow these steps:
    1. Identify if the file contains significant logic changes.
    2. Summarize the changes in the diff in clear and concise English, within 100 words.
    3. Provide actionable suggestions if there are any issues in the code.

    Once you have decided on the changes, for any TODOs, create a Github issue.
    And send the summary of the PR review to """
    + channel_id
    + """ channel on Slack. Slack doesn't have markdown, so send a plain text message.
    Also add the comprehensive review to the PR as a comment.
    """
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


# Create assistant with configurable OpenRouter model
def create_assistant(
    model="google/gemma-3-12b-it:free",
):  # Default to Claude 3.5 Sonnet
    assistant = openrouter_client.beta.assistants.create(
        name="PR Review Assistant",
        description="An assistant to help you with reviewing PRs",
        instructions=code_review_assistant_prompt,
        model=model,  # Use OpenRouter model identifier
        tools=pr_agent_tools,
    )
    return assistant


# Initialize assistant with desired OpenRouter model
assistant = create_assistant(model="anthropic/claude-3.5-sonnet")  # Change as needed
print(f"Assistant is ready with model: {assistant.model}")

# Create trigger listener
listener = composio_toolset.create_trigger_listener()


# Trigger handler for new PRs
@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    try:
        # Extract code to review from event payload
        code_to_review = str(event.payload)

        # Create new thread
        thread = openrouter_client.beta.threads.create()
        openrouter_client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=code_to_review
        )

        # Provide thread URL for debugging (note: OpenRouter might not have a playground)
        url = f"https://openrouter.ai/playground?assistant={assistant.id}&thread={thread.id}"
        print("Visit this URL to view the thread (if supported): ", url)

        # Execute assistant run
        run = openrouter_client.beta.threads.runs.create(
            thread_id=thread.id, assistant_id=assistant.id
        )

        # Handle tool calls and wait for completion
        composio_toolset.wait_and_handle_assistant_tool_calls(
            client=openrouter_client,
            run=run,
            thread=thread,
        )

    except Exception as e:
        print(f"Error reviewing PR: {str(e)}")


# Start listener
print("Listener started!")
print("Create a PR to get the review")
try:
    listener.wait_forever()
except KeyboardInterrupt:
    print("Listener stopped by user")
