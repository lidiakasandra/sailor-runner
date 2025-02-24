from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState
import websockets
import asyncio
import uuid

app = FastAPI()
tasks = {}

# Example WebSocket route to create new task and assign it a task_id
@app.websocket("/ws")
async def iniciate_task(websocket: WebSocket):
    await websocket.accept()
    task_data = await websocket.receive_text()

    # Generate a new task_id and store it
    task_id = str(uuid.uuid4())
    tasks[task_id] = {"main_ws": websocket, "updates_ws": None, "update_buffer": []}
    
    # Start task execution in the background
    asyncio.create_task(execute_task(task_id, task_data))

    # Keep the WebSocket connection open
    try:
        while True:
            # Here you can listen for any incoming messages from the client if needed
            data = await websocket.receive_text()
            print(f"Received NEW data: {data}")
    except WebSocketDisconnect:
        print(f"Client disconnected from task {task_id}")
        del tasks[task_id]

@app.websocket("/ws/{task_id}/updates")
async def update_task(websocket: WebSocket, task_id):
    await websocket.accept()

    # Store the WebSocket for updates in the task dictionary
    if task_id not in tasks:
        await websocket.send_text("Task not found.")
        await websocket.close()
        return

    tasks[task_id]["updates_ws"] = websocket

    # Send buffered updates if any
    while tasks[task_id]["update_buffer"]:
        message = tasks[task_id]["update_buffer"].pop(0)
        await websocket.send_text(message)

    try:
        # Keep connection open for updates
        while True:
            await asyncio.sleep(1)  # Just to keep it alive
    except WebSocketDisconnect:
        print(f"Update WebSocket for task {task_id} disconnected")
        tasks[task_id]["updates_ws"] = None

async def execute_task(task_id: str, task_data: str):
    # Execute the task and send updates via WebSocket.
    if task_id not in tasks:
        return
    
    main_ws = tasks[task_id]["main_ws"]
    updates_ws = tasks[task_id]["updates_ws"]

    print(f"Command: {task_data}")  # Debugging output
    if not task_data:
        raise ValueError("Command list is empty. Cannot execute subprocess.")
    try:
        process = await asyncio.create_subprocess_exec(
            *task_data.split(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        while main_ws.client_state != WebSocketState.CONNECTED:
            print("Waiting for main WebSocket to be connected...")
            await asyncio.sleep(0.5)  # Adjust the wait time as needed
        
        await main_ws.send_text(f"started {task_id}")

        while True:
            line = await process.stdout.readline()
            if not line:
                break
            message = line.decode('utf-8').strip()
            updates_ws = tasks[task_id]["updates_ws"]
            if updates_ws:
                await updates_ws.send_text(message)
            else:
                tasks[task_id]["update_buffer"].append(message)

    except WebSocketDisconnect:
        print(f"Client disconnected from task {task_id}")
        del tasks[task_id]

    # Send completion message
    completion_message = f"Task {task_id} completed"
    if tasks[task_id]["updates_ws"]:
        await tasks[task_id]["updates_ws"].send_text(completion_message)
    else:
        tasks[task_id]["update_buffer"].append(completion_message)

    # Cleanup
    await process.wait()
    del tasks[task_id]

