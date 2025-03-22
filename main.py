import os

from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from loguru import logger
from openai import OpenAI

channel_id = os.getenv("CHANNEL_ID", "")
if channel_id == "":
    channel_id = input("Enter Channel id:")


# # Get OpenRouter API key
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
if not openrouter_api_key:
    openrouter_api_key = input("Enter your OpenRouter API key: ")
    if not openrouter_api_key:
        raise ValueError(
            "OpenRouter API key is required. Set OPENROUTER_API_KEY in .env or enter it when prompted."
        )


logger.info("Starting the OpenAI client setup.")
openai_client = OpenAI(
    ## just comment out api_key and base_url if you want to use OpenAI
    ## make sure you change the `model` too if not using OpenRouter
    api_key=openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
)

logger.info("OpenAI client setup completed with API key provided.")

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
    + """ channel on slack. Slack doesn't have markdown and so send a plain text message.
        Also add the comprehensive review to the PR as a comment.
"""
)

composio_toolset = ComposioToolSet()
pr_agent_tools = composio_toolset.get_tools(
    actions=[
        Action.GITHUB_GET_A_PULL_REQUEST,
        Action.GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST,
        Action.GITHUB_CREATE_AN_ISSUE,
        Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
    ]
)

# Give openai access to all the tools
model = "qwen/qwq-32b:free"
logger.info(f"Model used - {model}")
assistant = openai_client.beta.assistants.create(
    name="PR Review Assistant",
    description="An assistant to help you with reviewing PRs",
    instructions=code_review_assistant_prompt,
    model="qwen/qwq-32b:free",
    tools=pr_agent_tools,
)
print("Assistant is ready")

## Create a trigger listener
listener = composio_toolset.create_trigger_listener()


## Triggers when a new PR is opened
@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    logger.info("New PR event received.")
    logger.debug(f"Event payload: {event.payload}")

    # Using the information from Trigger, execute the agent
    code_to_review = str(event.payload)
    logger.debug(f"Code to review: {code_to_review}")

    thread = openai_client.beta.threads.create()
    logger.info(f"Created a new thread with ID: {thread.id}")

    openai_client.beta.threads.messages.create(
        thread_id=thread.id, role="user", content=code_to_review
    )
    logger.info("Message sent to the thread for review.")

    # Let's print our thread
    url = f"https://platform.openai.com/playground/assistants?assistant={assistant.id}&thread={thread.id}"
    logger.info(f"Visit this URL to view the thread: {url}")

    logger.info("Executing agent with integrations.")
    run = openai_client.beta.threads.runs.create(
        thread_id=thread.id, assistant_id=assistant.id
    )
    logger.info(f"Agent execution started with run ID: {run.id}")

    composio_toolset.wait_and_handle_assistant_tool_calls(
        client=openai_client,
        run=run,
        thread=thread,
    )
    logger.info("Handled assistant tool calls successfully.")


print("Listener started!")
print("Create a pr to get the review")
listener.wait_forever()
