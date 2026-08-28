from graph.schema import FundState, AnalystSignal
from graph.constants import AgentKey
from llm.prompt import FUNDAMENTAL_PROMPT
from llm.inference import agent_call
from apis.router import Router, APISource
from util.db_helper import get_db
from util.logger import logger


def fundamental_agent(state: FundState):
    """Fundamental analysis specialist focusing on company profitability, growth, cashflow and financial health."""
    agent_name = AgentKey.FUNDAMENTAL
    ticker = state["ticker"]
    llm_config = state["llm_config"]
    portfolio_id = state["portfolio"].id

    # Get db instance
    db = get_db()

    logger.log_agent_status(agent_name, ticker, "Fetching financial metrics")

    # Get the financial metrics
    router = Router(APISource.ALPHA_VANTAGE)
    try:
        fundamentals = router.get_us_stock_fundamentals(ticker=ticker)
    except Exception as e:
        logger.error(f"Failed to fetch financial metrics for {ticker}: {e}")
        return state
    
    prompt = FUNDAMENTAL_PROMPT.format(fundamentals=fundamentals.model_dump_json())
    signal = agent_call(
        prompt=prompt, 
        llm_config=llm_config, 
        pydantic_model=AnalystSignal)
    
    # save signal
    logger.log_signal(agent_name, ticker, signal)
    db.save_signal(portfolio_id, agent_name, ticker, prompt, signal)
    
    return {"analyst_signals": [signal]}

