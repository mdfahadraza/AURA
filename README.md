   AURA

 Local AI Assistant with Reasoning, Planning & Memory:-
AURA is a local AI assistant designed to run on your own computer. It combines a local Large Language Model with reasoning, planning, short-term memory, and long-term semantic memory.
The long-term vision of AURA is to become an intelligent personal assistant capable of understanding users, reasoning about tasks, remembering useful information, and eventually interacting with Windows and Android systems.

Features:

~Local LLM inference — Runs an AI model locally instead of relying on cloud APIs.
~Streaming responses — Generates responses token-by-token for a real-time experience.
~Reasoning engine — Processes user requests and generates contextual responses.
~Task planning — Breaks requests into actionable plans.
~Short-term memory — Maintains recent conversation context.
~Long-term memory — Stores and retrieves useful user information using semantic search.
~Fact extraction — Identifies information that may be useful to remember.
~Offline-first architecture — Core AI functionality is designed to work locally.
~Future Windows & Android automation — Planned integration for intelligent device control.

Architecture-
                         ┌─────────────────┐
                         │      User       │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │      AURA       │
                         │   Main Loop     │
                         └────────┬────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
      ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
      │ Short-Term   │    │ Long-Term    │    │   Planner    │
      │   Memory     │    │   Memory     │    │              │
      └──────────────┘    └──────────────┘    └──────────────┘
              │                   │                   │
              └───────────────────┼───────────────────┘
                                  ▼
                         ┌─────────────────┐
                         │    Reasoning    │
                         │     Engine      │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │  Local LLM      │
                         │  GGUF / llama.cpp│
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │ Streaming Reply │
                         └─────────────────┘
Tech Stack
Python
PyTorch
llama.cpp / llama-cpp-python
Sentence Transformers
NumPy
SciPy
scikit-learn
SpeechRecognition
SoundDevice
SoundFile
pyttsx3
Requests
BeautifulSoup
Model

AURA is designed to work with local GGUF models through llama-cpp-python.
The current development configuration uses:

Qwen2.5-7B-Instruct-Q4_K_M

The model file is intentionally not included in this repository because large model files should not be committed to Git.
Place the downloaded model in:
AURA/
└── models/
    └── Qwen2.5-7B-Instruct-Q4_K_M.gguf

 The models/ directory is excluded through .gitignore.
Requirements-
 Windows 10/11
 Python 3.10+
 NVIDIA GPU recommended for CUDA acceleration
 8 GB RAM minimum
 More RAM/VRAM recommended for larger models
 
AURA can potentially run on CPU, depending on the model and configuration, although GPU acceleration is strongly recommended for a better experience.

Installation
 1. Clone the repository
 git clone https://github.com/mdfahadraza/AURA.git
 cd AURA
 2. Create a virtual environment
 python -m venv .venv

Activate it on Windows:

 .venv\Scripts\activate
 3. Install dependencies
 python -m pip install --upgrade pip
 pip install -r requirements.txt
 4. Add the model
 Download a compatible GGUF model and place it inside:
 models/
 For the current configuration:
 models/Qwen2.5-7B-Instruct-Q4_K_M.gguf
 5. Run AURA
 python main.py
 You should see:
 [AURA] Loading reasoning engine...
 [AURA] Loading memory systems...

=== AURA v2 Ready ===

You:

Type a message and AURA will generate a streaming response.

To exit:

exit
Project Structure
AURA/
│
├── main.py
├── reasoning_engine.py
├── planner.py
├── task_decomposer.py
│
├── short_term.py
├── long_term_vector.py
│
├── executor.py
├── os_commander.py
├── file_manager.py
├── web_scraper.py
│
├── stt_engine.py
├── tts_engine.py
├── kokoro_tts.py
├── sound_effects.py
│
├── server.py
├── roadmap_gui.py
│
├── launch_aura.bat
├── launch_aura.vbs
│
├── requirements.txt
├── .gitignore
└── README.md
Roadmap-
 Phase 1 — Core Intelligence
  Local LLM inference
  Streaming responses
  Short-term memory
  Long-term semantic memory
  Basic reasoning engine
  Task planning
  Fact extraction
 Phase 2 — Voice
  Text-to-speech foundation
  Speech-to-text foundation
  Fully integrated voice interaction
  Wake-word detection
  Continuous conversation mode
 Phase 3 — Windows Intelligence
  Application control
  File and folder operations
  System monitoring
  Process management
  Intelligent Windows automation
  Natural-language system commands
  Permission and safety layer
Phase 4 — Multimodal AI
 Vision capabilities
 Screenshot understanding
 OCR
 Visual UI interaction
 Document understanding
Phase 5 — Android
 Android companion
 Device communication
 Notification integration
 App automation
 Cross-device task execution
 Long-Term Vision

AURA aims to evolve from a local chatbot into an intelligent personal computing layer that can:
 Understand → Reason → Plan → Remember → Act
 The goal is to allow users to interact with their devices naturally rather than manually navigating menus, applications, and files.

Privacy-
AURA is designed with a local-first approach.

The core language model can run directly on the user's computer without requiring a cloud AI API. Users should review individual modules before enabling functionality that accesses files, applications, networks, microphones, or other system resources.
Performance. Performance depends heavily on the selected model, quantization, CPU, GPU, available VRAM, RAM, and context size. Large local models may require partial CPU/GPU offloading when available GPU memory is limited.

Contributing-
Contributions are welcome.
If you would like to contribute:
Fork the repository.
Create a feature branch.
Make your changes.
Test the changes locally.
Open a pull request.

Please keep contributions focused and document significant architectural changes.
License
This project is licensed under the MIT License.
See LICENSE for details.
Author
Mohammed Fahad Raza
Computer Science, Engineering Student
AURA is an evolving open-source project focused on building a capable, private, and locally running AI assistant.
