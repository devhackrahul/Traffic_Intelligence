/**
 * Fast Pothole Detection using multiple strategies
 * 1. YOLOv8 (primary - via yolo-detection.ts)
 * 2. Hugging Face API (fallback)
 * 3. Image analysis fallback
 */

interface DetectionResult {
  x: number
  y: number
  width: number
  height: number
  confidence: number
}

// TensorFlow.js removed - using YOLOv8 for better accuracy

// TensorFlow.js detection removed - using YOLOv8 instead for better accuracy

/**
 * Detect using Hugging Face API (fallback)
 */
async function detectWithHuggingFace(imageBase64: string): Promise<DetectionResult[]> {
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

    const response = await fetch(
      'https://api-inference.huggingface.co/models/facebook/detr-resnet-50',
      {
        method: 'POST',
        body: formData,
      }
    )

    if (response.ok) {
      const data = await response.json()
      if (Array.isArray(data)) {
        const detections: DetectionResult[] = []
        data.forEach((item: any) => {
          if (item.score > 0.5) {
            const box = item.box || {}
            detections.push({
              x: (box.xmin || 0) * 100,
              y: (box.ymin || 0) * 100,
              width: ((box.xmax || 0) - (box.xmin || 0)) * 100,
              height: ((box.ymax || 0) - (box.ymin || 0)) * 100,
              confidence: item.score,
            })
          }
        })
        return detections
      }
    }
  } catch (error) {
    console.warn('Hugging Face API failed:', error)
  }
  return []
}

/**
 * Advanced image analysis for pothole detection
 * Uses edge detection and pattern recognition
 */
function detectWithImageAnalysis(imageBase64: string): Promise<DetectionResult[]> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = img.width
      canvas.height = img.height
      const ctx = canvas.getContext('2d')
      if (!ctx) {
        resolve([])
        return
      }

      ctx.drawImage(img, 0, 0)
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const data = imageData.data

      // Simple edge detection and dark region detection (potholes are typically darker)
      const detections: DetectionResult[] = []
      const threshold = 80 // Dark threshold
      const minSize = 20 // Minimum pothole size in pixels

      // Scan for dark regions (potential potholes)
      for (let y = 0; y < canvas.height - minSize; y += 10) {
        for (let x = 0; x < canvas.width - minSize; x += 10) {
          let darkPixels = 0
          let totalPixels = 0

          for (let dy = 0; dy < minSize && y + dy < canvas.height; dy++) {
            for (let dx = 0; dx < minSize && x + dx < canvas.width; dx++) {
              const idx = ((y + dy) * canvas.width + (x + dx)) * 4
              const r = data[idx]
              const g = data[idx + 1]
              const b = data[idx + 2]
              const brightness = (r + g + b) / 3
              totalPixels++
              if (brightness < threshold) {
                darkPixels++
              }
            }
          }

          // Stricter threshold - require at least 50% dark pixels for potholes
          const darkRatio = darkPixels / totalPixels
          if (darkRatio > 0.5) {
            const confidence = Math.min(0.85, darkRatio * 1.2)
            // Only add if confidence is reasonably high
            if (confidence > 0.65) {
              detections.push({
                x: (x / canvas.width) * 100,
                y: (y / canvas.height) * 100,
                width: (minSize / canvas.width) * 100,
                height: (minSize / canvas.height) * 100,
                confidence: confidence,
              })
              // Skip ahead to avoid overlapping detections
              x += minSize
            }
          }
        }
      }

      // Remove overlapping detections
      const filtered = detections.filter((det, idx) => {
        for (let i = 0; i < idx; i++) {
          const other = detections[i]
          const overlap = 
            Math.abs(det.x - other.x) < 5 && 
            Math.abs(det.y - other.y) < 5
          if (overlap) return false
        }
        return true
      })

      // Further filter by confidence and limit results
      const highConfidence = filtered.filter(d => d.confidence > 0.7)
      resolve(highConfidence.slice(0, 5)) // Limit to 5 high-confidence detections
    }
    img.onerror = () => resolve([])
    img.src = imageBase64
  })
}

/**
 * Main detection function - uses YOLOv8 for best accuracy
 */
export async function detectPotholes(imageBase64: string): Promise<DetectionResult[]> {
  // Try YOLOv8 first (most accurate)
  if (typeof window !== 'undefined') {
    try {
      const { detectPotholesYOLO } = await import('./yolo-detection')
      const yoloResults = await detectPotholesYOLO(imageBase64)
      if (yoloResults.length > 0) {
        return yoloResults
      }
    } catch (error) {
      console.warn('YOLO detection failed, using fallback:', error)
    }
  }

  // Fallback to fast image analysis
  const fastResults = await detectWithImageAnalysis(imageBase64)
  if (fastResults.length > 0) {
    return fastResults
  }

  // Try Hugging Face API (fallback)
  const hfResults = await detectWithHuggingFace(imageBase64)
  if (hfResults.length > 0) {
    return hfResults
  }

  return fastResults
}

