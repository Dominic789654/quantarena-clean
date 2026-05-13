from agno.agent import Agent
from loguru import logger
from deepear.src.prompts.intent_agent import get_intent_analysis_instructions, get_intent_task
from deepear.src.schema.models import IntentAnalysis
from deepear.src.utils.json_utils import extract_json

class IntentAgent:
    """意图分析 Agent - 负责解析用户查询意图"""
    
    def __init__(self, model):
        self.model = model
        self.agent = Agent(
            model=model,
            instructions=[get_intent_analysis_instructions()],
            markdown=False,
            output_schema=IntentAnalysis if hasattr(model, 'response_format') else None
        )
        logger.info("🧠 IntentAgent initialized")

    def run(self, query: str) -> dict:
        """
        分析用户查询意图
        
        Args:
            query: 用户输入的查询字符串
            
        Returns:
            dict: 结构化的意图数据 (json)
        """
        try:
            logger.info(f"🧠 Analyzing intent for: {query}")
            response = self.agent.run(get_intent_task(query))
            content = response.content
            
            # 使用统一工具提取 JSON
            result = extract_json(content)            
            if not result:
               logger.warning("Intent output is not valid JSON, returning raw text in wrapper")
               result = {"intent_summary": content, "search_queries": [query], "is_specific_event": False, "keywords": [], "time_range": "recent"}

            # Optional: Validate against Pydantic model
            # try:
            #     obj = IntentAnalysis(**result)
            #     result = obj.model_dump()
            # except:
            #     pass

            logger.info(f"👉 Refined Intent: {result.get('intent_summary', 'N/A')}")
            return result
        except Exception as e:
            logger.warning(f"⚠️ Intent analysis failed: {e}")
            return {"intent_summary": f"Analysis failed for {query}", "search_queries": [query], "is_specific_event": False, "keywords": [], "time_range": "recent"}
