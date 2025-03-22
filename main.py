import os

from composio.client.collections import TriggerEventData
from composio_openai import Action, ComposioToolSet
from dotenv import load_dotenv
from loguru import logger
from openai import OpenAI, OpenAIError

# Load environment variables from .env file
load_dotenv()


def setup_api_client() -> OpenAI:
    """Setup and return API client (OpenRouter or OpenAI) with error handling"""
    openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    default_base_url = os.getenv("BASE_URL", "https://openrouter.ai/api/v1")

    if openrouter_api_key and default_base_url == "https://openrouter.ai/api/v1":
        try:
            client = OpenAI(api_key=openrouter_api_key, base_url=default_base_url)
            logger.info("OpenRouter client initialized successfully")
            return client
        except OpenAIError as e:
            logger.error(f"Failed to initialize OpenRouter client: {str(e)}")
            raise

    # Fallback to OpenAI
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        raise ValueError("OpenAI API key is required when not using OpenRouter")

    try:
        client = OpenAI(api_key=openai_api_key, base_url="https://api.openai.com/v1")
        logger.info("OpenAI client initialized successfully")
        return client
    except OpenAIError as e:
        logger.error(f"Failed to initialize OpenAI client: {str(e)}")
        raise


# Get channel ID
channel_id = os.getenv("CHANNEL_ID", "")
if not channel_id:
    channel_id = input("Enter Channel id: ").strip()
    if not channel_id:
        logger.error("Slack Channel ID is required")
        raise ValueError("Slack Channel ID is required")
logger.info(f"Using Slack channel ID: {channel_id}")

# Initialize API client
openai_client = setup_api_client()

# Define code review prompt
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

# Setup Composio tools
composio_toolset = ComposioToolSet()
pr_agent_tools = composio_toolset.get_tools(
    actions=[
        Action.GITHUB_GET_A_PULL_REQUEST,
        Action.GITHUB_CREATE_A_REVIEW_FOR_A_PULL_REQUEST,
        Action.GITHUB_CREATE_AN_ISSUE,
        Action.SLACK_SENDS_A_MESSAGE_TO_A_SLACK_CHANNEL,
    ]
)

# Create assistant
try:
    assistant = openai_client.beta.assistants.create(
        name="PR Review Assistant",
        description="An assistant to help you with reviewing PRs",
        instructions=code_review_assistant_prompt,
        model="qwen/qwq-32b:free",  # Using OpenRouter compatible model
        tools=pr_agent_tools,
    )
    logger.info(f"Assistant created successfully..")
    print("Assistant is ready")
except OpenAIError as e:
    logger.error(f"Failed to create assistant: {str(e)}")
    raise

# Create trigger listener
listener = composio_toolset.create_trigger_listener()


# Define callback for new PR events
@listener.callback(filters={"trigger_name": "github_pull_request_event"})
def review_new_pr(event: TriggerEventData) -> None:
    """Handle new PR review event"""
    try:
        logger.info("New pull request event received")
        code_to_review = str(event.payload)
        logger.debug(f"PR event payload: {code_to_review}")

        thread = openai_client.beta.threads.create()
        logger.info(f"Created new thread: {thread.id}")

        openai_client.beta.threads.messages.create(
            thread_id=thread.id, role="user", content=code_to_review
        )

        url = f"https://platform.openai.com/playground/assistants?assistant={assistant.id}&thread={thread.id}"
        logger.info(f"Review thread available at: {url}")
        print("Visit this URL to view the thread: ", url)

        # Start the review process
        run = openai_client.beta.threads.runs.create(
            thread_id=thread.id, assistant_id=assistant.id
        )
        logger.info(f"Started review run: {run.id}")

        # Handle tool calls
        composio_toolset.wait_and_handle_assistant_tool_calls(
            client=openai_client,
            run=run,
            thread=thread,
        )
        logger.info("PR review completed successfully")

    except Exception as e:
        logger.error(f"Error processing PR review: {str(e)}")
        raise


def main():
    """Main execution function"""
    try:
        logger.info("Starting PR Review System")
        print("Listener started!")
        print("Create a PR to get the review")
        listener.wait_forever()
    except Exception as e:
        logger.error(f"Application failed: {str(e)}")
        raise


if __name__ == "__main__":
    main()
