import os
import sys
import re
import subprocess
import time
from pathlib import Path

# Try imports
try:
    import google.generativeai as genai
    HAS_GEMINI = True
except ImportError:
    HAS_GEMINI = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

# Fix encoding issues on Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='ignore')
        sys.stderr.reconfigure(encoding='utf-8', errors='ignore')
    except AttributeError:
        pass

class AntigravityOrchestrator:
    def __init__(self, workspace_path=None):
        self.workspace = Path(workspace_path or os.getcwd()).resolve()
        self.global_config_dir = Path(r"C:\Users\deomo\.gemini\config")
        self.global_memory_path = self.global_config_dir / "AGENTS.md"
        self.local_memory_path = self.workspace / ".agents" / "AGENTS.md"
        
        # Setup models
        self.primary_model = "gemini-2.5-flash"
        self.thinking_model_fallback = "gemini-2.5-pro"  # Fallback to Pro if Claude API key is missing
        self.claude_model = "claude-3-5-sonnet-20240620"
        
        self.max_attempts = 3
        
        # API Keys configuration
        self.gemini_key = os.getenv("GEMINI_API_KEY")
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY")
        
        if self.gemini_key and HAS_GEMINI:
            genai.configure(api_key=self.gemini_key)

    def get_combined_memory(self):
        """Read and combine global and local project memories."""
        memories = []
        if self.global_memory_path.exists():
            try:
                memories.append(f"--- GLOBAL MEMORY ---\n{self.global_memory_path.read_text(encoding='utf-8')}")
            except Exception as e:
                print(f"[!] Warning: Could not read global memory: {e}")
                
        if self.local_memory_path.exists():
            try:
                memories.append(f"--- LOCAL WORKSPACE MEMORY ---\n{self.local_memory_path.read_text(encoding='utf-8')}")
            except Exception as e:
                print(f"[!] Warning: Could not read local memory: {e}")
                
        return "\n\n".join(memories)

    def check_memory(self, task_description):
        """Scan memory database to find lessons learned or previous mistakes related to the task."""
        print("[*] Retrieving relevant past memories and lessons learned...")
        combined_mem = self.get_combined_memory()
        if not combined_mem:
            return "No past memories or lessons learned found."

        # Simple semantic keyword matching for memory pruning (token savings)
        keywords = re.findall(r'\b\w{4,}\b', task_description.lower())
        relevant_sections = []
        
        for section in combined_mem.split("##"):
            section_lower = section.lower()
            match_count = sum(1 for kw in keywords if kw in section_lower)
            if match_count > 0:
                relevant_sections.append((match_count, section.strip()))
                
        # Sort by relevance
        relevant_sections.sort(key=lambda x: x[0], reverse=True)
        
        if not relevant_sections:
            # Fallback to returning a small portion of lessons learned
            lessons_match = re.search(r'## 🧠 2\. Lessons Learned.*?(?=##|$)', combined_mem, re.DOTALL | re.IGNORECASE)
            if lessons_match:
                return f"[PAST LESSONS]:\n{lessons_match.group(0)[:1500]}..."
            return "No directly relevant past lessons found in memory."
            
        # Compile relevant sections
        compiled_context = []
        for _, sect in relevant_sections[:3]:  # Top 3 relevant sections
            compiled_context.append(sect[:1000] + ("..." if len(sect) > 1000 else ""))
            
        return "[RELEVANT PAST MEMORY & LESSONS]:\n" + "\n\n".join(compiled_context)

    def call_llm(self, model_name, prompt):
        """Invokes the selected LLM based on model type."""
        # Use Claude if it's the target and we have credentials
        if "claude" in model_name and self.anthropic_key and HAS_ANTHROPIC:
            try:
                client = anthropic.Anthropic(api_key=self.anthropic_key)
                message = client.messages.create(
                    model=model_name,
                    max_tokens=4000,
                    messages=[{"role": "user", "content": prompt}]
                )
                return message.content[0].text
            except Exception as e:
                print(f"[!] Claude call failed: {e}. Falling back to Gemini Pro.")
                model_name = self.thinking_model_fallback

        # Gemini execution
        if HAS_GEMINI and self.gemini_key:
            # Map model names to standard Gemini API names
            gemini_model_map = {
                "gemini-2.5-flash": "models/gemini-2.5-flash",
                "gemini-2.5-pro": "models/gemini-2.5-pro"
            }
            mapped_model = gemini_model_map.get(model_name, "models/gemini-2.5-flash")
            try:
                model = genai.GenerativeModel(mapped_model)
                response = model.generate_content(prompt)
                return response.text
            except Exception as e:
                err_str = str(e)
                if "403" in err_str or "denied" in err_str.lower():
                    raise RuntimeError("Your environment variable GEMINI_API_KEY is restricted or has billing/quota limits. Please configure a valid key to run the local orchestrator script.")
                raise RuntimeError(f"Gemini API invocation failed: {e}")
        else:
            raise RuntimeError("No LLM client or API keys configured.")

    def run_code_and_get_stderr(self, code_content):
        """Saves code block to a temp file, runs it, and captures output/stderr."""
        # Extract code from markdown block if present
        code_match = re.search(r'```python(.*?)```', code_content, re.DOTALL)
        actual_code = code_match.group(1).strip() if code_match else code_content.strip()
        
        temp_file = self.workspace / "temp_code_test.py"
        try:
            temp_file.write_text(actual_code, encoding="utf-8")
            
            # Execute python script
            print("[*] Running script execution check...")
            res = subprocess.run(
                [sys.executable, str(temp_file)],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if res.returncode == 0:
                return True, res.stdout
            else:
                error_msg = res.stderr if res.stderr else res.stdout
                return False, error_msg
        except subprocess.TimeoutExpired:
            return False, "Execution timed out (exceeded 15s)."
        except Exception as e:
            return False, f"Failed to execute: {e}"
        finally:
            if temp_file.exists():
                try:
                    os.remove(temp_file)
                except:
                    pass

    def run_task(self, task_description):
        print(f"=== Antigravity Orchestrator Inception: {task_description} ===")
        
        # Step 1: Check past memory lessons
        memory_context = self.check_memory(task_description)
        
        # Initialize execution variables
        current_model = self.primary_model
        error_log = ""
        generated_code = ""
        
        # REPL execution loop
        for attempt in range(1, self.max_attempts + 1):
            print(f"\n--- [Attempt {attempt}/{self.max_attempts}] Current Model: {current_model} ---")
            
            # Prepare Prompt
            prompt = f"""
            Task to perform: {task_description}
            
            System guidelines/lessons learned to prevent errors:
            {memory_context}
            """
            if error_log:
                prompt += f"\n\nPrevious attempt failed with the following error output. Please analyze, fix the bug, and output the full corrected code:\n{error_log}"
            
            prompt += "\n\nProvide the complete working Python code. Wrap the code in a ```python block."
            
            try:
                generated_code = self.call_llm(current_model, prompt)
            except Exception as e:
                print(f"[!] Error calling LLM: {e}")
                if attempt == self.max_attempts:
                    break
                continue
                
            # Run code and verify errors
            success, output = self.run_code_and_get_stderr(generated_code)
            
            if success:
                print(f"[+] Task succeeded on attempt {attempt} using {current_model}!")
                print(f"Execution Output:\n{output}")
                
                # Update memory about the successful solution
                self.log_success_to_memory(task_description, current_model)
                return generated_code
            else:
                error_log = output
                print(f"[-] Execution failed. Stderr output:\n{error_log}")
                
                # Check model fallback conditions
                if attempt == self.max_attempts - 1:
                    if self.anthropic_key and HAS_ANTHROPIC:
                        print("\n[!] Primary model failed multiple times. Switching to Claude Sonnet (Thinking fallback) for the final attempt...")
                        current_model = self.claude_model
                    else:
                        print("\n[!] Primary model failed multiple times. Switching to Gemini Pro (Thinking fallback) for the final attempt...")
                        current_model = self.thinking_model_fallback
                else:
                    print("[*] Re-attempting self-correction with primary model...")
                    
                time.sleep(1)

        print("\n[!] Failed to solve task within max attempts. Intervention required.")
        return None

    def log_success_to_memory(self, task_description, model_used):
        """Triggers update_memory.py to record the successful solution."""
        update_script = self.global_config_dir / "scripts" / "update_memory.py"
        if update_script.exists():
            date_str = datetime.now().strftime("%Y-%m-%d") if 'datetime' in sys.modules else time.strftime("%Y-%m-%d")
            title = f"Antigravity Orchestrator Success"
            desc = f"Orchestrator solved task: '{task_description}' successfully using {model_used}."
            
            subprocess.run([
                sys.executable, str(update_script),
                f"[{date_str}] {title}", desc
            ])

if __name__ == "__main__":
    # Test execution
    if len(sys.argv) > 1:
        task = " ".join(sys.argv[1:])
    else:
        task = "import sys; print('Testing orchestrator execution loop: Success')"
        
    orchestrator = AntigravityOrchestrator()
    orchestrator.run_task(task)
