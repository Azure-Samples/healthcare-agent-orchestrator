# Agent Development Guide  
Everything you need to define new agents and give them custom tools.

## Table of Contents
- [Create / Modify Agents](#create--modify-agents)
- [Deploy Changes](#deploy-changes)
- [Adding tools (plugins) to your agents](#adding-tools-plugins-to-your-agents)

## Create / Modify Agents  

### Adding a New Agent
1. Open your scenario's `scenarios/<your-scenario>/config/agents.yaml` file
2. Add a new entry with the hyphen prefix `-` to create a new agent in the list
3. Include all required fields and any optional fields you need
4. Save the file

### Required YAML Fields  
| Field | Purpose |
|-------|---------|
| **name** | Unique identifier for the agent |
| **instructions** | System prompt the LLM receives |
| **description** | Brief text used in UI blurb and by orchestrator to determine when/how to use the agent |

### Optional Fields  
| Field | Purpose |
|-------|---------|
| **tools** | List of Semantic-Kernel plugin names the agent can call. See [tools](#adding-tools-plugins-to-your-agents) |
| **temperature** | LLM temperature (defaults to `0`) |
| **facilitator** | `true` → this agent moderates the conversation (only **one** allowed) |
| Other model parameters | e.g., `graph_rag_url`, `graph_rag_index_name`, `top_p`, `max_tokens` |

### Example Agent
```yaml
# scenarios/Orchestrator/config/agents.yaml
- name: patienteducator
  instructions: |
    You are a patient-education specialist. Your goals are to:
      - Detect jargon and explain it in ≤60 words at a 5th-grade level.  
      - Maintain a glossary and provide summaries on demand.  
      - End every response with 'back to you: *Orchestrator*'.
  description: |
    Translates medical jargon into plain English, keeps a glossary, and
    summarizes conversations for patients.
  tools:
    - name: patient_data
  temperature: 0.25
```

### Add a Custom Icon (Optional)
1. Place the PNG/SVG in `infra/botIcons/`  
2. Reference it inside `infra/modules/botservice.bicep`


## Deploy Changes

1. Save your updated YAML and plugin code.  
2. Run the standard deployment:  
```bash
azd up          # Azure best-practice: deploy infra + code together
```
3. Install/refresh the Teams app package if new agents or icons were added:  
```bash
uploadPackage.sh ./output <chatId|meetingLink> [tenantId]
```

## Adding tools (plugins) to your agents  

### Understanding Tools and Function Calling

Tools are Semantic-Kernel **plugins** that extend your agent's capabilities beyond text generation. Function calling enables an AI agent to interact with external tools, APIs, or code in a controlled and structured way. Instead of generating plain text instructions, the agent can "call" predefined functions with specific parameters as part of its reasoning and decision-making process.

During runtime, the framework automatically discovers any plugin that exposes a `create_plugin()` factory function. These plugins serve as the bridge between your agent's reasoning capabilities and external systems or data sources. For detailed information on developing Semantic Kernel plugins, see the [official documentation](https://learn.microsoft.com/en-us/semantic-kernel/concepts/plugins/?pivots=programming-language-python).  Below are some basics to get you started.

### Provided Tools
| Plugin | Function |
|--------|----------|
| `content_export` | Export tumor board summary to Word |
| `clinical_trials` | Search clinicaltrials.gov |
| `cxr_report_gen` | Run Microsoft CxrReportGen on images |
| `graph_rag` | RAG search of research papers |
| `med_image_insight` | Malignancy probability (MedImageInsight) |
| `med_image_parse` | Tumour sizing (MedImageParse) |
| `patient_data` | Timeline + Q&A over patient notes |


### Creating and Attaching Custom Tools to your Agents

1. Create either:
  - Single file: `src/<SCENARIO>/tools/my_new_tool_plugin.py` with `create_plugin()` function
  - Package: `src/<SCENARIO>/tools/my_new_tool_plugin/__init__.py` with `create_plugin()` function + other files
  - OpenAPI: an OpenAPI specification. See PatientStatus definition in `src/default/config/agents.yaml` and OpenAPI specification `src/default/config/openapi/time_api.yaml` as an example for adding OpenAPI service as tools.

The factory function must return your tool instance. The framework will automatically discover and load properly structured tools referenced in agent configs.

2. Reference the tool in your agent configuration  
   Open your scenario’s `src/<SCENARIO>/config/agents.yaml` and list the plugin under the
   agent’s `tools:` section:

   ```yaml
   - name: <AgentName>
     # …other agent fields…
     tools:
       - name: <plugin_package>
         type: <function | openapi>
         openapi_document_path: <path or url (openapi only)>
         server_url_override: <url (openapi only)>
   ```

### Optimizing Agent Fields for Tool Integration

#### Instruction Field
Tell the agent explicitly WHEN to use its tool, explain WHY the tool exists, provide output handling guidance and end with a hand-off phrase.

**WHEN to use the tool example:**
```yaml
Before proceeding, ensure you have the following information:
  age (str): The age of the patient.
  biomarker (str): The biomarker information of the patient.
  # ...more fields...
```

**WHY the tool exists example:**
```yaml
# MedicalResearch agent:
* Your responses must be based solely on the data retrieved using the Microsoft GraphRAG tool.
...
# ReportCreation agent:
You are an AI agent that assembles a tumor board Word document using information previously prepared by other agents.
```

**HOW to handle output example:**
```yaml 
# ClinicalTrials agent - detailed response structure:
3. Format the trial ID using a markdown link. For example, if the trial ID is "NCT123456", format it as [NCT123456](https://clinicaltrials.gov/study/NCT123456).
4. Present the results in a clear and concise manner, including the trial ID, title, and an explanation of why the patient is eligible for the trial.
```

**Hand-off example**
```yaml
# Common to almost all agents:
- After replying, yield control by saying: **"back to you: Orchestrator"**.
```

#### Description Field

The Orchestrator scans these descriptions when deciding which agent to call for a user request, so clarity here directly affects routing accuracy.

```yaml
# PatientHistory - standard format:
A patient history agent. **You provide**: patient timeline and can answer information regarding the patient that you typically find in patient notes or history. **You need** a patient ID provided by the user.

# ClinicalTrials agent - mentions dependency:
An agent providing information on clinical trials. **You provide**: information on clinical trials. **You need**: patient status from PatientStatus.
```

### Agent with a Tool Plugin Example

> src/<SCENARIO>/tools/weather_app.py:
```python

def create_plugin(plugin_config: PluginConfiguration) -> Kernel:
    return WeatherPlugin(plugin_config.kernel, plugin_config.chat_ctx)


class WeatherPlugin:
    def __init__(self, kernel: Kernel, chat_ctx: ChatContext):
        self.kernel = kernel
        self.chat_ctx = chat_ctx
        self.base_url = "https://wttr.in"

    @kernel_function()
    async def current_weather_zip(self, zip_code: str) -> str:
        url = f"{self.base_url}/{zip_code}?format=j1"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                resp.raise_for_status()
                data = await resp.json()

        cur = data["current_condition"][0]
        return json.dumps(cur)
```


> scenarios/<scenario>/config/agents.yaml:
```yaml

...
- name: Weather
  instructions: |
    You are an AI agent that reports the current weather for a U.S. ZIP code.
    - Always call the `current_weather_zip` tool to fetch data.  
    - If no ZIP code is provided, ask the user for it.  
    - Return: “Temperature: NN °F – Condition: <description>”.  
    - After replying, yield control by saying: **“back to you: Orchestrator”**.
  temperature: 0
  tools:
    - name: weather_app
  description: |
    Supplies current temperature and conditions. **Requires**: ZIP code.
```

### Agent with a OpenAPI Plugin Example
Agent can be configured to call OpenAPI services as tools. The following configuration demonstrates the PatientStatus agent using an OpenAPI service that returns current time to calculate age. Replace PatientStatus configuration in `src/scenarios/default/config/agents.yaml` with the following configuration to see the OpenAPI plugin in action. Run `azd deploy` to deploy changes.

```yaml
- name: PatientStatus
  instructions: |
    You are an AI agent that provides the patient's current status. Make sure to explicitly mention these characteristics before presenting the patient's current status.
      'age':
      'patient_gender':
      'staging':
      'primary site':
      'histology':
      'biomarkers'
      'treatment history':
      'ecog performance status':

    Don't proceed unless you have all of this information. 
    You may infer this information from the conversation if it is available.
    If date of birth is available, calculate the age using the `time_plugin`.
    If this information is not available, ask PatientHistory specifically for the missing information.
    DO:
      Ask PatientHistory. EXAMPLE: "*PatientHistory*, can you provide me with the patient's #BLANK?. Try to infer the information if not available".
  tools:
    - name: time_plugin
      type: openapi
      openapi_document_path: scenarios/default/config/openapi/time_api.yaml
      server_url_override: http://localhost:8000 # Using localhost since Time API is deployed locally.
  description: |
    A PatientStatus agent. You provide current status of a patient using. **You provide**: current status of a patient. **You need**: age, staging, primary site, histology, biomarkers, treatment history, ecog performance status. This can be obtained by PatientHistory.
```

From Teams, send the following message to the PatientStatus agent.

```
@PatientStatus what's the age if date of birth is 1965-12-01
```

PatientStatus should respond with patient's age based on date of birth.

```
age: 59 years old (calculated from date of birth 1965-12-01)
...
```

PatientStatus was able to calculate patient's age using the current time and the date of birth.

## Next Steps

* [Define your own scenario](./scenarios.md)