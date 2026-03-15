"""
Firestore collection/document schema reference for the storyteller database.

This file no longer defines SQLAlchemy models. It serves as documentation
for the Firestore document structure used by crud.py.

Collections
-----------
sessions/{session_id}
    status: str
    created_at: datetime
    updated_at: datetime

    Sub-collections:
        conversations/main
            transcript: str
            created_at: datetime

        story/main
            special_instructions: str
            created_at: datetime

        scenes/scene_{i}
            scene_index: int
            text: str
            summary: str
            narration_minio_key: str | None
            created_at: datetime

            Sub-collections:
                subscenes/sub_{j}
                    sub_index: int
                    image_prompt: str
                    video_prompt: str
                    image_minio_key: str | None
                    video_minio_key: str | None
                    created_at: datetime

        characters/{auto_id}
            name: str
            description: str
            image_minio_key: str | None
            created_at: datetime

        props/{auto_id}
            name: str
            description: str
            created_at: datetime

        pipeline_steps/{auto_id}
            step: str
            status: str
            message: str
            started_at: datetime | None
            finished_at: datetime | None

        edit_history/{auto_id}
            user_message: str
            reasoning: str
            dirty_keys: list[str]
            created_at: datetime

        errors/{auto_id}
            step: str | None
            message: str
            created_at: datetime

page_views/{auto_id}
    session_id: str | None
    page: str
    created_at: datetime
"""
