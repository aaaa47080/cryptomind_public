"""
Forum API request models.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class CreatePostRequest(BaseModel):
    """Create post payload."""

    board_slug: str = Field(..., description="Board slug")
    category: str = Field(
        ..., description="Post category: analysis/question/tutorial/news/chat/insight"
    )
    title: str = Field(..., max_length=200, description="Post title")
    content: str = Field(..., max_length=10000, description="Post content")
    tags: Optional[List[str]] = Field(None, max_length=5, description="Post tags")
    # TON Connect payment (Web DApp)
    order_token: Optional[str] = Field(
        None, description="Signed TON order binding this post payment to the user"
    )
    comment: Optional[str] = Field(
        None, description="On-chain memo used to locate the TON transfer"
    )
    payment_tx_hash: Optional[str] = Field(
        None, description="Blockchain transaction hash (fallback)"
    )


class UpdatePostRequest(BaseModel):
    """Update post payload."""

    title: Optional[str] = Field(None, max_length=200)
    content: Optional[str] = Field(None, max_length=10000)
    category: Optional[str] = None


class AddCommentRequest(BaseModel):
    """Add comment payload."""

    type: str = Field(..., description="Comment type: push/boo/comment")
    content: Optional[str] = Field(None, max_length=100, description="Comment content")
    parent_id: Optional[int] = Field(None, description="Parent comment ID")


class CreateTipRequest(BaseModel):
    # TON Connect payment (Web DApp)
    order_token: Optional[str] = Field(
        None, description="Signed TON order binding this tip payment to the user"
    )
    comment: Optional[str] = Field(
        None, description="On-chain memo used to locate the TON transfer"
    )
    tx_hash: Optional[str] = Field(None, description="Blockchain tx hash (fallback)")
    amount: float = Field(..., gt=0, description="Tip amount (from /api/config/prices)")


class TipOrderRequest(BaseModel):
    """Request a TON payment order for tipping a post."""

    amount: Optional[float] = Field(
        None, gt=0, description="Tip amount in TON (defaults to configured price)"
    )
