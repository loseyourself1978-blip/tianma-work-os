import AppKit

/// Geometry is in screen points, then converted by StageView to its current
/// window. Dock/menu/notch exclusions are intersected, never guessed or added twice.
enum StageGeometry {
    struct Toolbar {
        let backdrop, title, subtitle, wardrobe, truth, boundary: NSRect
        let actions: [NSRect]
    }
    static func safeScreenRect(frame:NSRect, visible:NSRect, insets:NSEdgeInsets) -> NSRect {
        let inset = NSRect(x:frame.minX+insets.left,y:frame.minY+insets.bottom,
                           width:max(0,frame.width-insets.left-insets.right),
                           height:max(0,frame.height-insets.top-insets.bottom))
        return frame.intersection(visible).intersection(inset)
    }
    static func art(in bounds:NSRect, below controls:NSRect) -> NSRect {
        let bottom=bounds.minY+35
        return NSRect(x:bounds.minX+24,y:bottom,width:max(1,bounds.width-48),
                      height:max(1,min(bounds.maxY-35,controls.minY-12)-bottom))
    }
    static func toolbar(in safe:NSRect, actionCount:Int) -> Toolbar {
        let width = max(1,min(1000,safe.width-16))
        let x = safe.minX+8, top = safe.maxY-8
        let inner = max(1,width-24)
        let columns = max(1,min(max(1,actionCount),Int(inner/116)))
        let rows = max(1,(actionCount+columns-1)/columns)
        let height = 148+CGFloat(rows)*36
        let backdrop = NSRect(x:x,y:top-height,width:width,height:height)
        func row(_ fromTop:CGFloat,_ height:CGFloat,_ width:CGFloat? = nil) -> NSRect {
            NSRect(x:x+12,y:top-fromTop-height,width:width ?? inner,height:height)
        }
        let cell = inner/CGFloat(columns)
        let actions = (0..<actionCount).map { i in
            NSRect(x:x+12+CGFloat(i%columns)*cell,y:top-144-CGFloat(i/columns+1)*36,
                   width:cell-5,height:30)
        }
        return Toolbar(backdrop:backdrop,title:row(8,24),subtitle:row(36,18),
                       wardrobe:row(58,28,min(390,inner)),truth:row(90,22),
                       boundary:row(116,20),actions:actions)
    }
}

func runStageGeometryTests() throws {
    func require(_ condition:Bool) throws { if !condition { throw PreviewError.invalidManifest } }
    let screen = NSRect(x:200,y:100,width:1440,height:900)
    let notch = NSEdgeInsets(top:32,left:0,bottom:0,right:0)
    let fixtures = [NSRect(x:200,y:180,width:1440,height:788),
                    NSRect(x:280,y:100,width:1360,height:868),
                    NSRect(x:200,y:100,width:1360,height:868),
                    NSRect(x:200,y:100,width:1440,height:868)]
    for visible in fixtures {
        let safe = StageGeometry.safeScreenRect(frame:screen,visible:visible,insets:notch)
        try require(visible.contains(safe) && screen.contains(safe))
        let layout = StageGeometry.toolbar(in:safe,actionCount:7)
        try require(safe.contains(layout.backdrop) && layout.backdrop.maxY == safe.maxY-8)
        let character = StageGeometry.art(in:screen,below:layout.backdrop)
        try require(!character.intersects(layout.backdrop) && screen.contains(character))
        for rect in layout.actions+[layout.title,layout.subtitle,layout.wardrobe,layout.truth,layout.boundary] {
            try require(layout.backdrop.contains(rect))
        }
        for i in 0..<layout.actions.count { for j in 0..<i {
            try require(!layout.actions[i].intersects(layout.actions[j]))
        }}
    }
    let narrow = NSRect(x:0,y:80,width:640,height:480)
    let layout = StageGeometry.toolbar(in:narrow,actionCount:7)
    try require(narrow.contains(layout.backdrop))
    try require(layout.actions[0].minY > layout.actions[6].minY)
    print("PASS: top toolbar fixtures for Dock left/right/bottom/autohide, notch and narrow display")
}
