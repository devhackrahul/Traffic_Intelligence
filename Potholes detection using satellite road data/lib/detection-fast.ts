/**
 * Ultra-fast pothole detection using optimized image analysis
 * This is a lightweight alternative that works entirely client-side
 */

interface DetectionResult {
  x: number
  y: number
  width: number
  height: number
  confidence: number
}

/**
 * Fast pothole detection using computer vision techniques
 * Optimized for speed and accuracy
 */
export async function detectPotholesFast(imageBase64: string): Promise<DetectionResult[]> {
  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      const ctx = canvas.getContext('2d', { willReadFrequently: true })
      if (!ctx) {
        resolve([])
        return
      }

      canvas.width = img.width
      canvas.height = img.height
      ctx.drawImage(img, 0, 0)

      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height)
      const detections = analyzeImageForPotholes(imageData, canvas.width, canvas.height)
      resolve(detections)
    }
    img.onerror = () => resolve([])
    img.src = imageBase64
  })
}

function analyzeImageForPotholes(
  imageData: ImageData,
  width: number,
  height: number
): DetectionResult[] {
  const data = imageData.data
  const detections: DetectionResult[] = []
  const visited = new Set<string>()

  // Parameters for pothole detection
  const darkThreshold = 70 // Potholes are typically darker
  const minRegionSize = 15 // Minimum pothole size
  const maxRegionSize = 200 // Maximum pothole size
  const step = 5 // Sampling step for performance

  // Scan image for dark regions (potential potholes)
  for (let y = 0; y < height - minRegionSize; y += step) {
    for (let x = 0; x < width - minRegionSize; x += step) {
      const key = `${Math.floor(x / 20)}_${Math.floor(y / 20)}`
      if (visited.has(key)) continue

      // Check if this region is a potential pothole
      const region = analyzeRegion(data, x, y, width, height, minRegionSize, darkThreshold)
      
      if (region.isPothole) {
        visited.add(key)
        
        // Expand region to find full extent
        const bounds = expandRegion(
          data,
          x,
          y,
          width,
          height,
          minRegionSize,
          maxRegionSize,
          darkThreshold
        )

        if (bounds.width >= minRegionSize && bounds.width <= maxRegionSize &&
            bounds.height >= minRegionSize && bounds.height <= maxRegionSize) {
          detections.push({
            x: (bounds.x / width) * 100,
            y: (bounds.y / height) * 100,
            width: (bounds.width / width) * 100,
            height: (bounds.height / height) * 100,
            confidence: Math.min(0.95, region.confidence),
          })
        }
      }
    }
  }

  // Remove overlapping detections
  return filterOverlaps(detections)
}

function analyzeRegion(
  data: Uint8ClampedArray,
  startX: number,
  startY: number,
  width: number,
  height: number,
  size: number,
  threshold: number
): { isPothole: boolean; confidence: number } {
  let darkPixels = 0
  let totalPixels = 0
  let variance = 0
  const brightnesses: number[] = []

  for (let dy = 0; dy < size && startY + dy < height; dy++) {
    for (let dx = 0; dx < size && startX + dx < width; dx++) {
      const idx = ((startY + dy) * width + (startX + dx)) * 4
      const r = data[idx]
      const g = data[idx + 1]
      const b = data[idx + 2]
      const brightness = (r + g + b) / 3
      
      brightnesses.push(brightness)
      totalPixels++
      
      if (brightness < threshold) {
        darkPixels++
      }
    }
  }

  // Calculate variance (potholes have higher variance due to shadows)
  const avg = brightnesses.reduce((a, b) => a + b, 0) / brightnesses.length
  variance = brightnesses.reduce((sum, b) => sum + Math.pow(b - avg, 2), 0) / brightnesses.length

  const darkRatio = darkPixels / totalPixels
  const isPothole = darkRatio > 0.35 && variance > 200 // Potholes are dark with texture
  
  return {
    isPothole,
    confidence: Math.min(0.95, darkRatio * 1.5 + (variance / 1000)),
  }
}

function expandRegion(
  data: Uint8ClampedArray,
  startX: number,
  startY: number,
  width: number,
  height: number,
  minSize: number,
  maxSize: number,
  threshold: number
): { x: number; y: number; width: number; height: number } {
  let x = startX
  let y = startY
  let w = minSize
  let h = minSize

  // Expand right
  while (x + w < width && w < maxSize) {
    let darkCount = 0
    for (let dy = 0; dy < h && y + dy < height; dy++) {
      const idx = ((y + dy) * width + (x + w)) * 4
      const brightness = (data[idx] + data[idx + 1] + data[idx + 2]) / 3
      if (brightness < threshold) darkCount++
    }
    if (darkCount / h > 0.3) {
      w++
    } else {
      break
    }
  }

  // Expand down
  while (y + h < height && h < maxSize) {
    let darkCount = 0
    for (let dx = 0; dx < w && x + dx < width; dx++) {
      const idx = ((y + h) * width + (x + dx)) * 4
      const brightness = (data[idx] + data[idx + 1] + data[idx + 2]) / 3
      if (brightness < threshold) darkCount++
    }
    if (darkCount / w > 0.3) {
      h++
    } else {
      break
    }
  }

  return { x, y, width: w, height: h }
}

function filterOverlaps(detections: DetectionResult[]): DetectionResult[] {
  const filtered: DetectionResult[] = []
  
  for (const det of detections) {
    let isOverlapping = false
    
    for (const existing of filtered) {
      const overlapX = Math.max(0, Math.min(det.x + det.width, existing.x + existing.width) - Math.max(det.x, existing.x))
      const overlapY = Math.max(0, Math.min(det.y + det.height, existing.y + existing.height) - Math.max(det.y, existing.y))
      const overlapArea = overlapX * overlapY
      const detArea = det.width * det.height
      const existingArea = existing.width * existing.height
      
      // If overlap is more than 30% of either detection, consider it overlapping
      if (overlapArea / Math.min(detArea, existingArea) > 0.3) {
        isOverlapping = true
        // Keep the one with higher confidence
        if (det.confidence > existing.confidence) {
          const index = filtered.indexOf(existing)
          filtered[index] = det
        }
        break
      }
    }
    
    if (!isOverlapping) {
      filtered.push(det)
    }
  }
  
  return filtered
}


