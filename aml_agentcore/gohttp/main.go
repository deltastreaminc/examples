package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/bedrockagentcore"
	"github.com/google/uuid"
)

const agentArn = "***"

type InvokeRequest struct {
	Prompt  string `json:"prompt"`
	AgentID string `json:"agentId"`
	AliasID string `json:"aliasId"`
}

type InvokeResponse struct {
	Response string `json:"response"`
	Error    string `json:"error,omitempty"`
}

var client *bedrockagentcore.Client

func main() {
	// Initialize AWS SDK
	cfg, err := config.LoadDefaultConfig(context.TODO())
	if err != nil {
		log.Fatal("Unable to load SDK config:", err)
	}
	client = bedrockagentcore.NewFromConfig(cfg)

	// Serve static files
	http.HandleFunc("/", serveHome)

	// API endpoint
	http.HandleFunc("/invoke", handleInvoke)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8081"
	}

	log.Printf("Server starting on port %s", port)
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}

func serveHome(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(htmlContent))
}

func handleInvoke(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	var req InvokeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		sendError(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	if req.Prompt == "" {
		sendError(w, "prompt is required", http.StatusBadRequest)
		return
	}

	response, err := invokeAgent(r.Context(), req.Prompt)
	if err != nil {
		sendError(w, fmt.Sprintf("Agent invocation failed: %v", err), http.StatusInternalServerError)
		return
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(InvokeResponse{Response: response})
}

var sessionID = fmt.Sprintf("session-%s", uuid.New().String())

func invokeAgent(ctx context.Context, prompt string) (string, error) {
	// Prepare the payload
	payload := map[string]interface{}{
		"prompt": prompt,
	}
	payloadBytes, err := json.Marshal(payload)
	if err != nil {
		return "", fmt.Errorf("failed to marshal payload: %w", err)
	}

	// Generate a unique session ID

	input := &bedrockagentcore.InvokeAgentRuntimeInput{
		AgentRuntimeArn:  aws.String(agentArn),
		RuntimeSessionId: aws.String(sessionID),
		Payload:          payloadBytes,
		ContentType:      aws.String("application/json"),
		Accept:           aws.String("text/event-stream"), // Request SSE format
	}

	response, err := client.InvokeAgentRuntime(ctx, input)
	if err != nil {
		return "", fmt.Errorf("failed to invoke agent: %w", err)
	}

	// The response is in SSE (Server-Sent Events) format
	if response.Response == nil {
		return "", fmt.Errorf("received empty response from agent")
	}

	// Parse the SSE stream
	b, err := io.ReadAll(response.Response)
	if err != nil {
		return "", fmt.Errorf("failed to read response body: %w", err)
	}

	fullResponse, err := parseSSEResponse(b)
	if err != nil {
		return "", fmt.Errorf("failed to parse SSE response: %w", err)
	}

	// Optionally, you can log additional metadata
	log.Printf("Session ID: %s", aws.ToString(response.RuntimeSessionId))
	log.Printf("Content Type: %s", aws.ToString(response.ContentType))

	return fullResponse, nil
}

func parseSSEResponse(data []byte) (string, error) {
	var fullText strings.Builder
	scanner := bufio.NewScanner(bytes.NewReader(data))

	for scanner.Scan() {
		line := scanner.Text()

		// SSE lines start with "data: "
		if strings.HasPrefix(line, "data: ") {
			// Remove "data: " prefix
			content := strings.TrimPrefix(line, "data: ")

			// Remove quotes if present
			content = strings.Trim(content, "\"")

			// Append to full text
			fullText.WriteString(content)
		}
	}

	if err := scanner.Err(); err != nil {
		return "", fmt.Errorf("error reading SSE stream: %w", err)
	}

	// Unescape the string to convert \n to actual newlines
	result := fullText.String()
	result = strings.ReplaceAll(result, "\\n", "\n")
	result = strings.ReplaceAll(result, "\\t", "\t")
	result = strings.ReplaceAll(result, "\\r", "\r")

	return result, nil
}

func getSessionID() *string {
	sessionID := "session-" + fmt.Sprintf("%d", os.Getpid())
	return &sessionID
}

func sendError(w http.ResponseWriter, message string, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(InvokeResponse{Error: message})
}

const htmlContent = `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AWS AgentCore Invoker</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 16px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            max-width: 800px;
            width: 100%;
            padding: 40px;
        }

        h1 {
            color: #333;
            margin-bottom: 10px;
            font-size: 28px;
        }

        .subtitle {
            color: #666;
            margin-bottom: 30px;
            font-size: 14px;
        }

        .form-group {
            margin-bottom: 20px;
        }

        label {
            display: block;
            color: #555;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }

        input, textarea {
            width: 100%;
            padding: 12px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: border-color 0.3s;
            font-family: inherit;
        }

        input:focus, textarea:focus {
            outline: none;
            border-color: #667eea;
        }

        textarea {
            resize: vertical;
            min-height: 100px;
        }

        button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px 32px;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: transform 0.2s, box-shadow 0.2s;
            width: 100%;
        }

        button:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(102, 126, 234, 0.4);
        }

        button:disabled {
            opacity: 0.6;
            cursor: not-allowed;
        }

        .response-container {
            margin-top: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            display: none;
        }

        .response-container.show {
            display: block;
        }

        .response-container h3 {
            color: #333;
            margin-bottom: 12px;
            font-size: 18px;
        }

        .response-text {
            color: #555;
            line-height: 1.6;
            white-space: pre-wrap;
            word-wrap: break-word;
        }

        .error {
            background: #fee;
            border-left-color: #e53e3e;
        }

        .error h3 {
            color: #e53e3e;
        }

        .loading {
            display: none;
            text-align: center;
            margin-top: 20px;
            color: #667eea;
        }

        .loading.show {
            display: block;
        }

        .spinner {
            border: 3px solid #f3f3f3;
            border-top: 3px solid #667eea;
            border-radius: 50%;
            width: 40px;
            height: 40px;
            animation: spin 1s linear infinite;
            margin: 0 auto 10px;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>AWS Bedrock AgentCore Invoker</h1>
        <p class="subtitle">Interact with your AWS Bedrock AgentCore</p>
        
        <form id="agentForm">
            <div class="form-group">
                <label for="prompt">Prompt</label>
                <textarea id="prompt" placeholder="Enter your question or instruction" required></textarea>
            </div>
            
            <button type="submit" id="submitBtn">Invoke Agent</button>
        </form>

        <div class="loading" id="loading">
            <div class="spinner"></div>
            <p>Invoking agent...</p>
        </div>
        
        <div class="response-container" id="responseContainer">
            <h3>Response</h3>
            <div class="response-text" id="responseText"></div>
        </div>
    </div>

    <script>
        const form = document.getElementById('agentForm');
        const loading = document.getElementById('loading');
        const responseContainer = document.getElementById('responseContainer');
        const responseText = document.getElementById('responseText');
        const submitBtn = document.getElementById('submitBtn');

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            
            const prompt = document.getElementById('prompt').value;

            loading.classList.add('show');
            responseContainer.classList.remove('show');
            submitBtn.disabled = true;

            try {
                const response = await fetch('/invoke', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ prompt })
                });

                const data = await response.json();
                
                loading.classList.remove('show');
                responseContainer.classList.add('show');
                
                if (data.error) {
                    responseContainer.classList.add('error');
                    responseText.textContent = data.error;
                } else {
                    responseContainer.classList.remove('error');
                    responseText.textContent = data.response;
                }
            } catch (error) {
                loading.classList.remove('show');
                responseContainer.classList.add('show', 'error');
                responseText.textContent = 'Network error: ' + error.message;
            } finally {
                submitBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
`
