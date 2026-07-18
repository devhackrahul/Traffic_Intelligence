# Quick Setup Guide

## Installation

1. **Install dependencies:**
   ```bash
   npm install
   ```

2. **Set up environment variables:**
   The `.env.local` file is already created with your Google Maps API key. If you need to update it:
   ```
   NEXT_PUBLIC_GOOGLE_MAPS_API_KEY=your_api_key_here
   ```

3. **Run the development server:**
   ```bash
   npm run dev
   ```

4. **Open your browser:**
   Navigate to [http://localhost:3000](http://localhost:3000)

## Features

### Detection Methods (in order of speed):
1. **Fast Image Analysis** - Client-side, instant detection using computer vision
2. **TensorFlow.js COCO-SSD** - AI model running in browser (loads on first use)
3. **Hugging Face API** - Cloud-based detection (fallback)

### Usage:
1. Allow location access when prompted
2. Choose Video or Image input
3. For video: Click "Start Camera" or "Upload Video"
4. For image: Upload an image file
5. Click "Detect Potholes" to start detection
6. View results with bounding boxes on the preview

## Performance Tips

- The app uses multiple detection methods for best results
- First detection may take a few seconds (model loading)
- Subsequent detections are much faster
- For best accuracy, ensure good lighting and clear road images

## Troubleshooting

- **Camera not working**: Check browser permissions
- **No detections**: Try with better lighting or clearer road images
- **Map not loading**: Verify Google Maps API key is correct
- **Slow detection**: The first run loads models, subsequent runs are faster


