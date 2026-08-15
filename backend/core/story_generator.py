from sqlalchemy.orm import Session

from google import genai
from google.genai import types

from core.config import settings
from core.prompts import STORY_PROMPT
from models.story import Story, StoryNode
from core.models import StoryLLMResponse, StoryNodeLLM
from dotenv import load_dotenv

load_dotenv()

class StoryGenerator:

    @classmethod
    def _get_client(cls):
        return genai.Client(api_key=settings.gemini_api_key)

    @classmethod
    def generate_story(cls, db: Session, session_id: str, theme: str = "fantasy")-> Story:
        client = cls._get_client()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=f"Create the story with this theme: {theme}",
            config=types.GenerateContentConfig(
                system_instruction=STORY_PROMPT,
                response_mime_type="application/json",
                response_schema=StoryLLMResponse,
                max_output_tokens=8192,
                thinking_config=types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MEDIUM
                ),
            ),
        )

        story_structure = response.parsed
        if story_structure is None:
            if not response.text:
                raise ValueError("Gemini returned an empty story response.")
            story_structure = StoryLLMResponse.model_validate_json(response.text)

        story_db = Story(title=story_structure.title, session_id=session_id)
        db.add(story_db)
        db.flush()

        root_node_data = story_structure.rootNode
        if isinstance(root_node_data, dict):
            root_node_data = StoryNodeLLM.model_validate(root_node_data)

        cls._process_story_node(db, story_db.id, root_node_data, is_root=True)

        db.commit()
        return story_db

    @classmethod
    def _process_story_node(cls, db: Session, story_id: int, node_data: StoryNodeLLM, is_root: bool = False) -> StoryNode:
        node = StoryNode(
            story_id=story_id,
            content=node_data.content if hasattr(node_data, "content") else node_data["content"],
            is_root=is_root,
            is_ending=node_data.isEnding if hasattr(node_data, "isEnding") else node_data["isEnding"],
            is_winning_ending=node_data.isWinningEnding if hasattr(node_data, "isWinningEnding") else node_data["isWinningEnding"],
            options=[]
        )
        db.add(node)
        db.flush()

        if not node.is_ending and (hasattr(node_data, "options") and node_data.options):
            options_list = []
            for option_data in node_data.options:
                next_node = option_data.nextNode

                if isinstance(next_node, dict):
                    next_node = StoryNodeLLM.model_validate(next_node)

                child_node = cls._process_story_node(db, story_id, next_node, False)

                options_list.append({
                    "text": option_data.text,
                    "node_id": child_node.id
                })

            node.options = options_list

        db.flush()
        return node
