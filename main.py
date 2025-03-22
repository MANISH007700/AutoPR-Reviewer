import os

import dotenv
from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from loguru import logger
from openai import OpenAI, OpenAIError

dotenv.load_dotenv()

channel_id = os.getenv("CHANNEL_ID", "")
if not channel_id:
    channel_id = input("Enter Slack Channel ID: ")

openai_client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"), base_url="https://openrouter.ai/api/v1"
)

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

composio_toolset = ComposioToolSet()
pr_agent_tools = composio_toolset.get_tools(
    actions=[
        Action.GITHUB_GET_A_PULL_REQUEST,
        Action.GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST,
        Action.GITHUB_CREATE_AN_ISSUE,
        Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
    ]
)

try:
    assistant = openai_client.beta.assistants.create(
        name="PR Review Assistant",
        description="An assistant to help you with reviewing PRs",
        instructions=code_review_assistant_prompt,
        model="openai/gpt-4o",  # Verify this model name
        tools=pr_agent_tools,
    )
    logger.info("Assistant created successfully")
except OpenAIError as e:
    logger.error(f"Failed to create assistant: {e}")
    exit(1)

listener = composio_toolset.create_trigger_listener()


@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    try:
        logger.info(f"Event payload: {event.payload}")
        code_to_review = str(event.payload)
        print("Code to Review ---- ", code_to_review)

        thread = openai_client.beta.threads.create()
        logger.info(f"Thread created: {thread.id}")

        openai_client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=code_to_review
        )
        logger.info("Message posted to thread")

        run = openai_client.beta.threads.runs.create(
            thread_id=thread.id, assistant_id=assistant.id
        )
        logger.info(f"Run started: {run}")

        composio_toolset.wait_and_handle_assistant_tool_calls(
            client=openai_client,
            run=run,
            thread=thread,
        )
        logger.success("Message Sent on Slack.")
    except Exception as e:
        logger.error(f"Error in review_new_pr: {e}")
        raise


logger.info("Listener started -------- ")
logger.info("Create a PR to get the review")
listener.wait_forever()
