# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.

import json
import logging
import os
from azure.identity import ManagedIdentityCredential
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor
import yaml

logger = logging.getLogger(__name__)

def setup_otel_logging():
    """Configure OpenTelemetry logging and tracing for Application Insights."""
    os.environ["OTEL_EXPERIMENTAL_RESOURCE_DETECTORS"] = "azure_app_service"
    trace.set_tracer_provider(TracerProvider())
    tracer_provider = trace.get_tracer_provider()

    # Configure Azure Monitor Exporter
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        exporter = AzureMonitorTraceExporter(
            connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
        )
        span_processor = BatchSpanProcessor(exporter)
        tracer_provider.add_span_processor(span_processor)

    # Instrument FastAPI
    FastAPIInstrumentor().instrument()

    # Instrument Logging
    LoggingInstrumentor().instrument(set_logging_format=True)

    # Set root logger level for all logs
    logging.getLogger().setLevel(logging.DEBUG)

def setup_logging(log_level=logging.DEBUG) -> None:
    # Set up autogen logging and ensure logs are propagated to root logger for Azure Monitor
    from autogen_core import TRACE_LOGGER_NAME
    autogen_logger = logging.getLogger(TRACE_LOGGER_NAME)
    autogen_logger.setLevel(log_level)
    autogen_logger.propagate = True
    
    #setup semantic kernel logging
    from semantic_kernel.utils.logging import setup_logging
    setup_logging()
    
    #setup logging for opentelemetry
    setup_otel_logging()

    logger = logging.getLogger(__name__)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Configure Azure Monitor if connection string is set
    if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        credential = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID"))
        configure_azure_monitor(
            credential=credential,
            logger=logging.getLogger(__name__),
            connection_string=os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"),
            logging_exporter_enabled=True,
            tracing_exporter_enabled=True,
            metrics_exporter_enabled=True,
            enable_live_metrics=True,
            formatter=formatter
        )

    # Avoid duplicate handlers
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        logger.addHandler(console_handler)
    logger.setLevel(log_level)

    # Ensure all loggers propagate to root for Azure Monitor
    for name in logging.root.manager.loggerDict:
        logging.getLogger(name).propagate = True


def load_agent_config(scenario: str) -> dict:
    src_dir = os.path.dirname(os.path.abspath(__file__))
    scenario_directory = os.path.join(src_dir, f"scenarios/{scenario}/config")

    agent_config_path = os.path.join(scenario_directory, "agents.yaml")

    with open(agent_config_path, "r", encoding="utf-8") as f:
        agent_config = yaml.safe_load(f)
    bot_ids = json.loads(os.getenv("BOT_IDS"))
    hls_model_endpoints = json.loads(os.getenv("HLS_MODEL_ENDPOINTS"))
    for agent in agent_config:
        agent["bot_id"] = bot_ids.get(agent["name"])
        agent["hls_model_endpoint"] = hls_model_endpoints
        if agent.get("addition_instructions"):
            for file in agent["addition_instructions"]:
                with open(os.path.join(scenario_directory, file)) as f:
                    agent["instructions"] += f.read()

    return agent_config


class DefaultConfig:
    """ Bot Configuration """

    def __init__(self, botId):
        self.APP_ID = botId
        self.APP_PASSWORD = os.environ.get("MicrosoftAppPassword", "")
        self.APP_TYPE = os.environ.get("MicrosoftAppType", "MultiTenant")
        self.APP_TENANTID = os.environ.get("MicrosoftAppTenantId", "")
