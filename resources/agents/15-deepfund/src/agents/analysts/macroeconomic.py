from graph.schema import FundState, AnalystSignal
from graph.constants import AgentKey
from llm.prompt import MACROECONOMIC_PROMPT
from llm.inference import agent_call
from apis.router import Router, APISource
from util.db_helper import get_db
from util.logger import logger

def macroeconomic_agent(state: FundState):
    """Macroeconomic analysis specialist focusing on economic indicators."""
    agent_name = AgentKey.MACROECONOMIC
    ticker = state["ticker"]
    llm_config = state["llm_config"]
    portfolio_id = state["portfolio"].id

    # Get db instance
    db = get_db()

    logger.log_agent_status(agent_name, ticker, "Fetching macro economic indicators")

    # Get the economic indicators
    router = Router(APISource.ALPHA_VANTAGE)
    try:
        economic_indicators = router.get_us_economic_indicators()
    except Exception as e:
        logger.error(f"Failed to fetch economic indicators for {ticker}: {e}")
        return state
    
    prompt = MACROECONOMIC_PROMPT.format(economic_indicators=economic_indicators)
    signal = agent_call(
        prompt=prompt, 
        llm_config=llm_config, 
        pydantic_model=AnalystSignal)
    
    # save signal
    logger.log_signal(agent_name, ticker, signal)
    db.save_signal(portfolio_id, agent_name, ticker, prompt, signal)
    
    return {"analyst_signals": [signal]}