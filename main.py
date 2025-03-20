import os

import dotenv
from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from loguru import logger
from openai import OpenAI

# Load environment variables from .env file
dotenv.load_dotenv()

# Get Slack channel ID from environment, prompt user if not set
channel_id = os.getenv("CHANNEL_ID", "")
if not channel_id:
    channel_id = input("Enter Slack Channel ID: ")

# Initialize OpenAI client (expects OPENAI_API_KEY in environment)
openai_client = OpenAI()

# Define the assistant's prompt with instructions
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

# Initialize Composio toolset (expects COMPOSIO_API_KEY in environment if required)
composio_toolset = ComposioToolSet()

# Define tools for the assistant to use
pr_agent_tools = composio_toolset.get_tools(
    actions=[
        Action.GITHUB_GET_A_PULL_REQUEST,
        Action.GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST,
        Action.GITHUB_CREATE_AN_ISSUE,
        Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
    ]
)

# Create the OpenAI assistant with tools
assistant = openai_client.beta.assistants.create(
    name="PR Review Assistant",
    description="An assistant to help you with reviewing PRs",
    instructions=code_review_assistant_prompt,
    model="gpt-4o",
    tools=pr_agent_tools,
)

logger.info("Assistant is ready")

# Create a trigger listener for GitHub pull request events
listener = composio_toolset.create_trigger_listener()


# Callback function to review new PRs
@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    # Convert event payload to string for review
    code_to_review = str(event.payload)

    # Create a new thread with OpenAI
    thread = openai_client.beta.threads.create()
    openai_client.beta.threads.messages.create(
        thread_id=thread.id, role="user", content=code_to_review
    )

    logger.info("A PR is generated.")

    # Start assistant execution
    run = openai_client.beta.threads.runs.create(
        thread_id=thread.id, assistant_id=assistant.id
    )

    # Handle tool calls (e.g., Slack posting, GitHub issue creation)
    composio_toolset.wait_and_handle_assistant_tool_calls(
        client=openai_client,
        run=run,
        thread=thread,
    )


logger.info("Listener started -------- ")
logger.info("Create a PR to get the review")
listener.wait_forever()
