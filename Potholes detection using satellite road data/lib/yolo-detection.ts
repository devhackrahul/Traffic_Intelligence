/**
 * YOLOv8 Pothole Detection
 * Uses the latest YOLO model for accurate pothole detection
 */

interface DetectionResult {
  x: number
  y: number
  width: number
  height: number
  confidence: number
}

interface YOLODetection {
  x: number
  y: number
  width: number
  height: number
  confidence: number
  class: string
}

/**
 * Detect potholes using YOLOv8 via Roboflow API (fastest and most accurate)
 * Alternative: Can use ONNX.js with local model for offline detection
 */
export async function detectPotholesYOLO(imageBase64: string): Promise<DetectionResult[]> {
  try {
    // Method 1: Try Roboflow API (fastest, most accurate)
    const roboflowResults = await detectWithRoboflow(imageBase64)
    if (roboflowResults.length > 0) {
      return roboflowResults
    }

    // Method 2: Try Hugging Face YOLOv8 API
    const hfResults = await detectWithHuggingFaceYOLO(imageBase64)
    if (hfResults.length > 0) {
      return hfResults
    }

    // Method 3: Fallback to local ONNX model if available
    return await detectWithONNX(imageBase64)
  } catch (error) {
    console.error('YOLO detection error:', error)
    return []
  }
}

/**
 * Detect using Roboflow API (Recommended - fastest and most accurate)
 * You can get a free API key from roboflow.com
 * For now, this is a placeholder - configure with your API key
 */
async function detectWithRoboflow(imageBase64: string): Promise<DetectionResult[]> {
  // Skip Roboflow if no API key configured
  // Uncomment and configure if you have a Roboflow API key
  return []
  
  /* 
  try {
    const base64Data = imageBase64.split(',')[1] || imageBase64
    const byteCharacters = atob(base64Data)
    const byteNumbers = new Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i)
    }
    const byteArray = new Uint8Array(byteNumbers)
    const blob = new Blob([byteArray], { type: 'image/jpeg' })

    const formData = new FormData()
    formData.append('file', blob, 'image.jpg')

    const response = await fetch(
      'https://detect.roboflow.com/YOUR_MODEL/YOUR_VERSION?api_key=YOUR_API_KEY',
      {
        method: 'POST',
        body: formData,
      }
    )

    if (response.ok) {
      const data = await response.json()
      return parseRoboflowResponse(data)
    }
  } catch (error) {
    console.warn('Roboflow API not available:', error)
  }
  return []
  */
}

/**
 * Detect using Hugging Face YOLOv8 Inference API
 * Uses the latest YOLOv8 model for accurate detection
 */
async function detectWithHuggingFaceYOLO(imageBase64: string): Promise<DetectionResult[]> {
  try {
    const base64Data = imageBase64.split(',')[1] || imageBase64
    const byteCharacters = atob(base64Data)
    const byteNumbers = new Array(byteCharacters.length)
    for (let i = 0; i < byteCharacters.length; i++) {
      byteNumbers[i] = byteCharacters.charCodeAt(i)
    }
    const byteArray = new Uint8Array(byteNumbers)
    const blob = new Blob([byteArray], { type: 'image/jpeg' })

    const formData = new FormData()
    formData.append('image', blob, 'image.jpg')

    // Using Ultralytics YOLOv8n (nano - fastest) or YOLOv8s (small - more accurate)
    // Try multiple endpoints for reliability
    const endpoints = [
      'https://api-inference.huggingface.co/models/ultralytics/yolov8n',
      'https://api-inference.huggingface.co/models/keremberke/yolov8m-pothole-segmentation',
    ]

    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          method: 'POST',
          body: formData,
        })

        if (response.ok) {
          const data = await response.json()
          const results = parseHuggingFaceYOLOResponse(data)
          if (results.length > 0) {
            return results
          }
        } else if (response.status === 503) {
          // Model is loading, wait and retry
          await new Promise(resolve => setTimeout(resolve, 2000))
          const retryResponse = await fetch(endpoint, {
            method: 'POST',
            body: formData,
          })
          if (retryResponse.ok) {
            const data = await retryResponse.json()
            const results = parseHuggingFaceYOLOResponse(data)
            if (results.length > 0) {
              return results
            }
          }
        }
      } catch (err) {
        continue // Try next endpoint
      }
    }
  } catch (error) {
    console.warn('Hugging Face YOLO API failed:', error)
  }
  return []
}

/**
 * Detect using ONNX.js with local YOLOv8 model
 * This is a placeholder - would require ONNX model file hosting
 * Currently using Hugging Face API instead for better compatibility
 */
async function detectWithONNX(imageBase64: string): Promise<DetectionResult[]> {
  // ONNX detection not implemented - using Hugging Face API instead
  return []
}

/**
 * Parse Roboflow API response
 */
function parseRoboflowResponse(data: any): DetectionResult[] {
  if (!data.predictions || !Array.isArray(data.predictions)) {
    return []
  }

  const detections: DetectionResult[] = []
  const imageWidth = data.image?.width || 640
  const imageHeight = data.image?.height || 640

  data.predictions.forEach((pred: any) => {
    // Filter for pothole class or high confidence detections
    if (pred.class === 'pothole' || pred.confidence > 0.5) {
      detections.push({
        x: ((pred.x - pred.width / 2) / imageWidth) * 100,
        y: ((pred.y - pred.height / 2) / imageHeight) * 100,
        width: (pred.width / imageWidth) * 100,
        height: (pred.height / imageHeight) * 100,
        confidence: pred.confidence,
      })
    }
  })

  return detections
}

/**
 * Parse Hugging Face YOLO response
 * Improved filtering to reduce false positives
 */
function parseHuggingFaceYOLOResponse(data: any): DetectionResult[] {
  if (!Array.isArray(data)) {
    return []
  }

  const detections: DetectionResult[] = []
  // Try to get actual image dimensions from the data (if available)
  // Hugging Face API returns array of detections, dimensions may be in metadata
  const imageWidth = 640 // Default, will use normalized coordinates
  const imageHeight = 640

  data.forEach((item: any) => {
    // Use higher confidence threshold to reduce false positives - only high confidence
    if (item.score && item.score > 0.7) {
      const box = item.box || item.bbox || {}
      
      // Handle different box formats
      let x: number, y: number, width: number, height: number
      
      if (box.xmin !== undefined) {
        // COCO format
        x = box.xmin
        y = box.ymin
        width = box.xmax - box.xmin
        height = box.ymax - box.ymin
      } else if (box.x !== undefined && box.width !== undefined) {
        // Center format
        x = box.x - box.width / 2
        y = box.y - box.height / 2
        width = box.width
        height = box.height
      } else {
        return // Skip invalid boxes
      }

      // Filter for pothole-related detections with stricter criteria
      const label = (item.label || item.class || '').toLowerCase()
      // Only accept pothole-related labels, not generic objects
      const isPotholeRelated = 
        label.includes('pothole') ||
        (label.includes('hole') && item.score > 0.75) ||
        (label.includes('crack') && item.score > 0.8)

      // Additional validation: potholes should have reasonable size and aspect ratio
      const minSize = 0.015 // 1.5% of image (smaller min to avoid tiny noise)
      const maxSize = 0.25 // 25% of image (smaller max to avoid huge detections)
      const normalizedWidth = width / imageWidth
      const normalizedHeight = height / imageHeight
      const aspectRatio = width / height
      
      // Potholes are typically roughly circular or slightly elongated
      // Filter out very narrow or very wide detections
      const validAspectRatio = aspectRatio > 0.3 && aspectRatio < 3.0
      const validArea = (normalizedWidth * normalizedHeight) > 0.0005 // Minimum area
      
      if (
        isPotholeRelated &&
        normalizedWidth > minSize &&
        normalizedHeight > minSize &&
        normalizedWidth < maxSize &&
        normalizedHeight < maxSize &&
        validAspectRatio &&
        validArea
      ) {
        detections.push({
          x: (x / imageWidth) * 100,
          y: (y / imageHeight) * 100,
          width: (width / imageWidth) * 100,
          height: (height / imageHeight) * 100,
          confidence: item.score,
        })
      }
    }
  })

  // Remove overlapping detections (NMS - Non-Maximum Suppression)
  return nonMaximumSuppression(detections)
}

/**
 * Non-Maximum Suppression to remove overlapping detections
 * Improved algorithm to better handle overlapping boxes
 */
function nonMaximumSuppression(detections: DetectionResult[], iouThreshold: number = 0.4): DetectionResult[] {
  if (detections.length === 0) return []

  // Sort by confidence (highest first)
  const sorted = [...detections].sort((a, b) => b.confidence - a.confidence)
  const selected: DetectionResult[] = []

  for (const det of sorted) {
    let shouldAdd = true
    
    for (const selectedDet of selected) {
      const iou = calculateIOU(det, selectedDet)
      
      // If overlap is significant, keep only the one with higher confidence
      if (iou > iouThreshold) {
        // If current detection has significantly higher confidence, replace
        if (det.confidence > selectedDet.confidence * 1.2) {
          const index = selected.indexOf(selectedDet)
          selected.splice(index, 1)
          break
        } else {
          shouldAdd = false
          break
        }
      }
      
      // Also check if boxes are very close (even if IOU is low)
      const centerDistance = Math.sqrt(
        Math.pow((det.x + det.width / 2) - (selectedDet.x + selectedDet.width / 2), 2) +
        Math.pow((det.y + det.height / 2) - (selectedDet.y + selectedDet.height / 2), 2)
      )
      const avgSize = Math.sqrt(det.width * det.height + selectedDet.width * selectedDet.height) / 2
      
      if (centerDistance < avgSize * 0.3 && iou > 0.2) {
        // Boxes are very close, keep only higher confidence
        if (det.confidence <= selectedDet.confidence) {
          shouldAdd = false
          break
        } else {
          const index = selected.indexOf(selectedDet)
          selected.splice(index, 1)
          break
        }
      }
    }
    
    if (shouldAdd) {
      selected.push(det)
    }
  }

  return selected
}

/**
 * Calculate Intersection over Union (IOU) between two bounding boxes
 */
function calculateIOU(box1: DetectionResult, box2: DetectionResult): number {
  const x1 = Math.max(box1.x, box2.x)
  const y1 = Math.max(box1.y, box2.y)
  const x2 = Math.min(box1.x + box1.width, box2.x + box2.width)
  const y2 = Math.min(box1.y + box1.height, box2.y + box2.height)

  const intersection = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
  const area1 = box1.width * box1.height
  const area2 = box2.width * box2.height
  const union = area1 + area2 - intersection

  return union > 0 ? intersection / union : 0
}

/**
 * Alternative: Use a public YOLOv8 inference API
 * This uses a free public API for YOLO detection
 */
export async function detectWithPublicYOLOAPI(imageBase64: string): Promise<DetectionResult[]> {
  try {
    const response = await fetch('https://api.yolov8.ai/predict', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        image: imageBase64,
        model: 'yolov8n',
        confidence: 0.5,
      }),
    })

    if (response.ok) {
      const data = await response.json()
      return parseYOLOAPIResponse(data)
    }
  } catch (error) {
    console.warn('Public YOLO API failed:', error)
  }
  return []
}

function parseYOLOAPIResponse(data: any): DetectionResult[] {
  if (!data.predictions || !Array.isArray(data.predictions)) {
    return []
  }

  return data.predictions
    .filter((pred: any) => pred.confidence > 0.5)
    .map((pred: any) => ({
      x: pred.x * 100,
      y: pred.y * 100,
      width: pred.width * 100,
      height: pred.height * 100,
      confidence: pred.confidence,
    }))
}

