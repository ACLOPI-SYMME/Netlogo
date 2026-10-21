extensions [csv]

globals [

  Simulated.Time
  Time-for-Possible-launching
  Mouse-Aux
  PosibleProducts
  temporalis

  W1-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W2-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W3A-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W3B-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W4-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W5-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W6-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W7-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W8-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W9-Indicator      ; 0: Segment Empty 1: Segment No-Empty
  W10-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W11-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W12-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W13-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W14-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W15-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W16-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W17-Indicator     ; 0: Segment Empty 1: Segment No-Empty
  W18-Indicator     ; 0: Segment Empty 1: Segment No-Empty

  operations
  OperationDuration
  distances

  DataFrameInfo
  DataFrameTemp

  EventFrameInfo
  EventFrameTemp

  Monorail.Infeed.Time
  Monorail.Outfeed.Time

  terminado


]

breed [nodes node]
nodes-own [
  Addressed.To.Node
]

breed [arrows arrow]

breed [sensors sensor]
sensors-own [Sensor.ID signal]

breed [products product]
products-own [
  Product.State                ; State of product Movement,
  ProductType
  Next.Product.Operation       ; Indicates the next operation to process
  ProductOperations            ; list of operations
  CurrentSequenceOrder         ; to be done or being done
  ProductPlannedStart
  ProductPlannedCompletion
  ProductRealStart
  ProductRealCompletion
  Last.Node
  Next.Node
  Heading.Workstation             ; Indicates the workstation that will get in when passes through it sensors/gates.
  Next.Product.status             ; Indicates if next operation was executed  1: yes   0: no
  Next.Product.Completion.Time    ; Indicates the time when the next.operation was completed

  Machine.Used
  NetlogoTurtle-ID
  speed-factor
  priority
  Platoon-Position
]

breed [machines machine]
machines-own [
  Machine.Name
  Machine.State               ; Machine.Processing or Idle
  Next.Completion
  Machine.Operations.Type
  Machine.Operations.Time
  Products.Queue
  Machine.Atractiveness
  Number.Products.Radio
]
directed-link-breed [conveyors conveyor]
conveyors-own [Default.position  Associated-Arrow]


to Setup

  clear-all
  reset-ticks
  set Time-for-Possible-launching 0
  ask patches [set pcolor white]
  set simulated.time 0
  set Mouse-Aux 0
  Layout.Creation
  set Monorail.Infeed.Time [37.5	36.9	82.8	39.1	37.5	40.9	42.8]
  set Monorail.Outfeed.Time [32.6	34.7	22.6	32.6	32.6	43.4	47.7]
  set PosibleProducts ["A" "I" "P" "B" "E" "L" "T"]

  set DataFrameInfo[]
  set DataFrameTemp[]

  set EventFrameInfo[]
  set EventFrameTemp[]

  set terminado "No"

end


to Go

  Moving.Product
  Product.Movement
  PotentialFields

  let Orden.test true ; true o False
  if(Orden.test = true)[
    let counter count products with [xcor >= 90 and xcor <= 115 and ycor >= 80 and ycor <= 110]
    if (simulated.time mod 100 <= 0.2 and count products with [Product.State != "death"] < 10 and counter = 0) [
      create.product one-of PosibleProducts
    ]
  ]

  if (Orden.test = false) [
  ]


  let logs  Interval.logs
  if (simulated.time mod logs <= 0.3 and ticks != 0) [PrintData]

  EventPassing



  if (ticks = 10000) [
    ExportData
    set terminado "Si"
    stop
  ]

  if(Time-for-Possible-launching > 0) [set Time-for-Possible-launching (Time-for-Possible-launching - 1)]
  tick

end

to ExportData

  let data-file (word "Results/Data/Data_" Interval.Logs "_" substring Modeling.type 0 3 "_R" substring Reactivity.Rule 4 6 "_" behaviorspace-run-number ".csv")
  let event-file (word "Results/Events/Event_" Interval.Logs "_" substring Modeling.type 0 3 "_R" substring Reactivity.Rule 4 6 "_" behaviorspace-run-number ".csv")

  csv:to-file data-file dataframeinfo
  csv:to-file event-file eventframeinfo

end

to EventMachineEntry [#1 #2]

  set EventFrameTemp lput simulated.time EventFrameTemp                                                      ; Tiempo de simulacion
  set EventFrameTemp lput #1 EventFrameTemp                                                                  ; Identificador Who que agente
  set EventFrameTemp lput [productType] of turtle #1 EventFrameTemp                                          ; Tipo de producto
  set EventFrameTemp lput "ProductEntersMachine" EventFrameTemp                                              ; Tipo de evento
  set EventFrameTemp lput [Label] of turtle #2 EventFrameTemp                                                ; Posicion del evento Maquina, nodo, sensor
  set EventFrameTemp lput [currentSequenceOrder] of turtle #1 EventFrameTemp                                 ; que operacion esta cuando ENTRA
  set EventFrameTemp lput [item currentSequenceOrder productoperations] of turtle #1 EventFrameTemp          ; que operacion es
  set EventFrameTemp lput [next.product.operation] of turtle #1 EventFrameTemp                               ; cual es la siguiente operacion
  set EventFrameTemp lput [heading.Workstation] of turtle #1 EventFrameTemp                                  ; a que maquina se dirije

  set EventFrameInfo lput EventFrameTemp EventFrameInfo
  set EventFrameTemp[]

end

to EventMachineExit [#1 #2]

  set EventFrameTemp lput simulated.time EventFrameTemp                                                      ; Tiempo de simulacion
  set EventFrameTemp lput #1 EventFrameTemp                                                                  ; Identificador Who que agente
  set EventFrameTemp lput [productType] of turtle #1 EventFrameTemp                                          ; Tipo de producto
  set EventFrameTemp lput "ProductExitsMachine" EventFrameTemp                                               ; Tipo de evento
  set EventFrameTemp lput [Label] of turtle (item 0 #2) EventFrameTemp                                       ; Posicion del evento Maquina, nodo, sensor
  set EventFrameTemp lput "XXX" EventFrameTemp                                 ; que operacion esta cuando SALE
  set EventFrameTemp lput "YYY" EventFrameTemp
  set EventFrameTemp lput [next.product.operation] of turtle #1 EventFrameTemp                               ; cual es la siguiente operacion
  set EventFrameTemp lput [heading.Workstation] of turtle #1 EventFrameTemp                                  ; a que maquina se dirije

  set EventFrameInfo lput EventFrameTemp EventFrameInfo
  set EventFrameTemp[]

end

to EventPassing

  let node.list [12 16 22 25 31 35 49 53 67 71 77 81 57 72 39 44]
  ask nodes with [member? who node.list][
    let close-products products in-radius 0.1
    if any? close-products [

      Let A [who] of one-of close-products
      Let B who
      set EventFrameTemp lput simulated.time EventFrameTemp                                                     ; Tiempo de simulacion
      set EventFrameTemp lput A EventFrameTemp                                                                  ; Identificador Who que agente
      set EventFrameTemp lput [productType] of turtle A EventFrameTemp                                          ; Tipo de producto
      set EventFrameTemp lput "PassingBy" EventFrameTemp                                                        ; Tipo de evento
      set EventFrameTemp lput (word "Node " who) EventFrameTemp                                                  ; Posicion del evento Maquina, nodo, sensor
      set EventFrameTemp lput [currentSequenceOrder] of turtle A EventFrameTemp                                 ; que operacion esta cuando PASA
      set EventFrameTemp lput [item currentSequenceOrder productoperations] of turtle A EventFrameTemp          ; que operacion es
      set EventFrameTemp lput [next.product.operation] of turtle A EventFrameTemp                               ; cual es la siguiente operacion
      set EventFrameTemp lput [heading.Workstation] of turtle A EventFrameTemp                                  ; a que maquina se dirije

      set EventFrameInfo lput EventFrameTemp EventFrameInfo
      set EventFrameTemp[]


    ]
  ]


end

to PrintData

  ; Block 0 (Parameters or control)
  set DataFrameTemp lput precision Simulated.time 0 DataFrameTemp
  set DataFrameTemp lput Reactivity.rule DataFrameTemp
  set DataFrameTemp lput Modeling.Type DataFrameTemp

  ; Block 1 (Global State)
  set DataFrameTemp lput count products with [Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput (count products with [Product.State != "death"] / 10)  DataFrameTemp
  set DataFrameTemp lput (count machines with [Machine.State =  "Machine.Processing"])  DataFrameTemp
  set DataFrameTemp lput (count products with [Product.State != "death"] - count machines with [Machine.State =  "Machine.Processing"])  DataFrameTemp
  set DataFrameTemp lput precision (mean [xcor] of products with [Product.State != "death"]) 2 DataFrameTemp
  set DataFrameTemp lput precision (sqrt (mean map [i -> (i - mean [xcor] of products with [Product.State != "death"]) ^ 2] [xcor] of products with [Product.State != "death"])) 2 DataFrameTemp
  set DataFrameTemp lput precision mean [ycor] of products with [Product.State != "death"] 2 DataFrameTemp
  set DataFrameTemp lput precision (sqrt (mean map [i -> (i - mean [ycor] of products with [Product.State != "death"]) ^ 2] [ycor] of products with [Product.State != "death"])) 2 DataFrameTemp
  set DataFrameTemp lput (sum [length productoperations] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (sum [length productrealcompletion] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (count products with [Product.State = "Wating"]) DataFrameTemp
  set DataFrameTemp lput ((sum [length productoperations] of products with [Product.State != "death"]) - (sum [length productrealcompletion] of products with [Product.State != "death"] - (count products with [Product.State = "Waiting"]))) DataFrameTemp

  set DataFrameTemp lput precision (sum [sum map [i -> item  ((read-from-string (last i)) - 1)  OperationDuration] productoperations] of products with [Product.State != "death"]) 2 DataFrameTemp
  set DataFrameTemp lput precision (sum [sum map [i -> (i - item (position i productrealcompletion) productrealstart)] productrealcompletion] of products with [Product.State != "death"]) 2 DataFrameTemp
  set DataFrameTemp lput precision (sum [simulated.time - last productrealstart] of products with [Product.State != "death" and product.state = "waiting"]) 2 DataFrameTemp
  set DataFrameTemp lput precision (sum [sum map [i -> item  ((read-from-string (last i)) - 1)  OperationDuration] (sublist productoperations (length productrealstart) (length productoperations))] of products with [Product.State != "death"]) 2 DataFrameTemp

  set DataFrameTemp lput count machines with [machine.state = "Machine.Processing"] DataFrameTemp
  set DataFrameTemp lput count machines with [machine.state != "Machine.Processing"] DataFrameTemp

  ; Block 2 (Products)
  set DataFrameTemp lput count products with [producttype = "B" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "E" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "L" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "T" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "A" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "I" and Product.State != "death"] DataFrameTemp
  set DataFrameTemp lput count products with [producttype = "P" and Product.State != "death"] DataFrameTemp

  let listEntropy[]
  if(count products with [producttype = "B" and Product.State != "death"] != 0)[set listEntropy lput "B" listEntropy]
  if(count products with [producttype = "E" and Product.State != "death"] != 0)[set listEntropy lput "E" listEntropy]
  if(count products with [producttype = "L" and Product.State != "death"] != 0)[set listEntropy lput "L" listEntropy]
  if(count products with [producttype = "T" and Product.State != "death"] != 0)[set listEntropy lput "T" listEntropy]
  if(count products with [producttype = "A" and Product.State != "death"] != 0)[set listEntropy lput "A" listEntropy]
  if(count products with [producttype = "I" and Product.State != "death"] != 0)[set listEntropy lput "I" listEntropy]
  if(count products with [producttype = "P" and Product.State != "death"] != 0)[set listEntropy lput "P" listEntropy]
  set DataFrameTemp lput precision (0 - (sum map [i -> ((count products with [producttype = i and Product.State != "death"] / count products with [Product.State != "death"])*(log (count products with [producttype = i and Product.State != "death"] / count products with [Product.State != "death"]) 2))] listEntropy)) 2 DataFrameTemp
  set DataFrameTemp lput precision (length listEntropy / 7) 2 DataFrameTemp
  set DataFrameTemp lput precision (sum map [i -> ([length productrealcompletion / (length productoperations)] of i)] (sort products with [Product.State != "death"])) 2 DataFrameTemp
  set DataFrameTemp lput precision (count products with [Product.State != "death"]) 2 DataFrameTemp
  set DataFrameTemp lput precision (((sum map [i -> ([length productrealcompletion / (length productoperations)] of i)] (sort products with [Product.State != "death"]))) / (count products with [Product.State != "death"])) 2 DataFrameTemp

  ; Block 3 (Machines)


  ask machine 186 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M1"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 187 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M2"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 188 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M3"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 189 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M4"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 190 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M5"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 191[
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M6"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]
    ask machine 192 [
    ifelse (Machine.state = "Machine.Processing")[
      set DataFrameTemp lput "Machine.Busy" DataFrameTemp
      set DataFrameTemp lput precision (next.completion - simulated.time) 3 DataFrameTemp
      set DataFrameTemp lput (count products in-radius 22 with [heading.workstation = "M7"]) DataFrameTemp
    ][
      set DataFrameTemp lput "Machine.Idle" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
      set DataFrameTemp lput "NaN" DataFrameTemp
    ]
  ]

  ; Block 4 (conveyors)

   set DataFrameTemp lput count products with [70 <= xcor and xcor <= 150 and 70 <= ycor and ycor <= 120] DataFrameTemp   ; M1
   set DataFrameTemp lput count products with [150 < xcor and xcor <= 210 and 88 <= ycor and ycor <= 120] DataFrameTemp   ; M2
   set DataFrameTemp lput count products with [200 <= xcor and xcor <= 250 and 60 < ycor and ycor < 88] DataFrameTemp     ; M3
   set DataFrameTemp lput count products with [150 < xcor and xcor <= 210  and 30 <= ycor and ycor <= 60] DataFrameTemp   ; M4
   set DataFrameTemp lput count products with [70 <= xcor and xcor <= 150 and 30 <= ycor and ycor < 70] DataFrameTemp     ; M5
   set DataFrameTemp lput count products with [2 <= xcor and xcor < 70 and 30 <= ycor and ycor < 70] DataFrameTemp        ; M6
   set DataFrameTemp lput count products with [2 <= xcor and xcor < 70 and 70 <= ycor and ycor <= 120] DataFrameTemp      ; M7


  ; Block 5 (KPI)

  set DataFrameTemp lput count machines with [machine.state = "Machine.Processing"] DataFrameTemp
  set DataFrameTemp lput count machines with [machine.state != "Machine.Processing"] DataFrameTemp
  set DataFrameTemp lput precision (count machines with [machine.state = "Machine.Processing"] / 7) 2 DataFrameTemp
  set DataFrameTemp lput count products with [Product.State != "death"] DataFrameTemP
  set DataFrameTemp lput count products with [70 <= xcor and xcor <= 150 and 70 <= ycor and ycor <= 120] DataFrameTemp   ; M1
  set DataFrameTemp lput count products with [150 < xcor and xcor <= 210 and 88 <= ycor and ycor <= 120] DataFrameTemp   ; M2
  set DataFrameTemp lput count products with [200 <= xcor and xcor <= 250 and 60 < ycor and ycor < 88] DataFrameTemp     ; M3
  set DataFrameTemp lput count products with [150 < xcor and xcor <= 210  and 30 <= ycor and ycor <= 60] DataFrameTemp   ; M4
  set DataFrameTemp lput count products with [70 <= xcor and xcor <= 150 and 30 <= ycor and ycor < 70] DataFrameTemp     ; M5
  set DataFrameTemp lput count products with [2 <= xcor and xcor < 70 and 30 <= ycor and ycor < 70] DataFrameTemp        ; M6
  set DataFrameTemp lput count products with [2 <= xcor and xcor < 70 and 70 <= ycor and ycor <= 120] DataFrameTemp      ; M7

  set DataFrameTemp lput precision mean [xcor] of products with [Product.State != "death"] 2 DataFrameTemp
  set DataFrameTemp lput precision(sqrt (mean map [i -> (i - mean [xcor] of products with [Product.State != "death"]) ^ 2] [xcor] of products with [Product.State != "death"])) 2 DataFrameTemp
  set DataFrameTemp lput precision mean [ycor] of products with [Product.State != "death"] 2 DataFrameTemp
  set DataFrameTemp lput precision(sqrt (mean map [i -> (i - mean [ycor] of products with [Product.State != "death"]) ^ 2] [ycor] of products with [Product.State != "death"])) 2 DataFrameTemp
  set DataFrameTemp lput (sum [length productoperations] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (sum [length productrealcompletion] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (count products with [Product.State = "Waiting"]) DataFrameTemp
  set DataFrameTemp lput ((sum [length productoperations] of products with [Product.State != "death"]) - (sum [length productrealcompletion] of products with [Product.State != "death"] - (count products with [Product.State = "Waiting"]))) DataFrameTemp
  set DataFrameTemp lput (sum [sum map [i -> item  ((read-from-string (last i)) - 1)  OperationDuration] productoperations] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (sum [sum map [i -> (i - item (position i productrealcompletion) productrealstart)] productrealcompletion] of products with [Product.State != "death"]) DataFrameTemp
  set DataFrameTemp lput (sum [simulated.time - last productrealstart] of products with [Product.State != "death" and product.state = "Waiting"]) DataFrameTemp
  set DataFrameTemp lput (sum [sum map [i -> item  ((read-from-string (last i)) - 1)  OperationDuration] (sublist productoperations (length productrealstart) (length productoperations))] of products with [Product.State != "death"]) DataFrameTemp




  set DataFrameInfo lput DataFrameTemp DataFrameInfo
  set DataFrameTemp []

end


to Layout.Creation

  Node.Creation
  Conveyor.Creation
  Direction.Arrows.Creation
  Set.Associated.Arrow
  Set.Default.Layout
  Set.Sensors
  Set.Machines
  Set.operations
  Set.distances.Machines
  Set.aditional.nodes


end

to Curved.Move [angle radius #1]

  if (#1 = "curve1") [
    if (([xcor] of Last.node = xcor) and ([ycor] of Last.node = ycor)) [lt 39.8]
    rt angle / 3
    fd 2.2 * radius * sin (angle / 2)
    rt angle / 3
  ]
  if (#1 = "curve2") [
    if (([xcor] of Last.node = xcor) and ([ycor] of Last.node = ycor)) [rt 25]
    lt angle / 2
    fd 2 * radius * sin (angle / 2)
    lt angle / 2
  ]
  if (#1 = "curve3") [
    if (([xcor] of Last.node = xcor) and ([ycor] of Last.node = ycor)) [lt 25]
    rt angle / 2
    fd 2 * radius * sin (angle / 2)
    rt angle / 2
  ]

  set xcor precision xcor 3
  set ycor precision ycor 3

end

to-report AgregateOperations [#1]
  let temp[]
  if(#1 = "B")[set temp (list "O8" "O1" "O1" "O1" "O2" "O2" "O3" "O5" "O9")]   ; without inspection
  if(#1 = "E")[set temp (list "O8" "O1" "O1" "O1" "O2" "O2" "O4" "O9")]        ; without inspection
  if(#1 = "L")[set temp (list "O8" "O1" "O1" "O1" "O3" "O3" "O5" "O5" "O9")]   ; without inspection
  if(#1 = "T")[set temp (list "O8" "O1" "O1" "O2" "O4"  "O9")]                 ; without inspection
  if(#1 = "A")[set temp (list "O8" "O1" "O1" "O1" "O2" "O4" "O3" "O5" "O9")]   ; without inspection
  if(#1 = "I")[set temp (list "O8" "O1" "O1" "O3" "O5"  "O9")]                 ; without inspection
  if(#1 = "P")[set temp (list "O8" "O1" "O1" "O2" "O4"  "O9")]                 ; without inspection


  report temp


end


to Create.product [#1]

  create-products 1 [
    move-to turtle 151
    set xcor xcor - 5
    set Last.Node node 93
    set Next.Node node 0
    face Next.Node
    set size 15
    set shape "0-plate"
    set color 98
    if (Product-Label? = true)[set label  (word #1 "(0%)") set label-color 96]

    set ProductType #1
    set product.state "Movement"
    set ProductOperations AgregateOperations #1
    set CurrentSequenceOrder 0
    set Next.Product.Completion.Time ""
    set Next.Product.Operation  "O8"
    set Heading.Workstation "M1"
    set ProductPlannedStart[]
    set ProductPlannedCompletion[]
    set ProductRealStart[]
    set ProductRealCompletion[]
    set Heading.Workstation "M1"
    set NetlogoTurtle-ID (count products - 1)
    set speed-factor 1
    set platoon-position 0 - 1
    set Machine.Used []
    set priority random (100 - 60 + 1) + 60
  ]

end

to-report minuscule [#1]
  let temp ""
  if(#1 = "B")[set temp "b"]
  if(#1 = "E")[set temp "e"]
  if(#1 = "L")[set temp "l"]
  if(#1 = "T")[set temp "t"]
  if(#1 = "A")[set temp "a"]
  if(#1 = "I")[set temp "i"]
  if(#1 = "P")[set temp "p"]

  report temp

end

to-report conversion [#1]

  let temp ""
  if(#1 = "A")[set temp 1]
  if(#1 = "I")[set temp 2]
  if(#1 = "P")[set temp 3]
  if(#1 = "B")[set temp 4]
  if(#1 = "E")[set temp 5]
  if(#1 = "L")[set temp 6]
  if(#1 = "T")[set temp 7]

  report temp

end


to Cheking.Machine.Completion

  ask machine 186 [                                                                            ; MACHINE 1
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 158 and ycor = [ycor] of sensor 158][

        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        ifelse(currentsequenceorder < length ProductOperations)[
          set Next.product.operation item currentsequenceorder ProductOperations

          if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
          if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
            ]
          if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]

          ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        ][



          ;die

          ; if the agent do not die
           setxy 2 2 set shape "circle" set size 1 set product.state "death" set label "" set color white


        ]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 2
        if (temporal > 98) [setxy 115 (117 - (3.5 * (100 -  temporal)))]
        if (temporal <= 98 and temporal >= 1) [setxy 115 110]
        if (temporal < 2) [setxy 115 (110 + (3.5 * (2 -  temporal)))]
      ]
    ]
  ]

 ask machine 187 [                                                                            ; MACHINE 2
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 159 and ycor = [ycor] of sensor 159][
        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
        if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 1
        if (temporal > 198) [setxy 193 (117 - (3.5 * (200 -  temporal)))]
        if (temporal <= 198 and temporal >= 2) [setxy 193 110]
        if (temporal < 2) [setxy 193 (110 + (3.5 * (2 -  temporal)))]
      ]
    ]
  ]


 ask machine 188 [                                                                            ; MACHINE 3
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 160 and ycor = [ycor] of sensor 160][

        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
          if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 1
        if (temporal > 198) [setxy 226 (55.4 + (3.5 * (200 -  temporal)))]
        if (temporal <= 198 and temporal >= 2) [setxy 226 62.4]
        if (temporal < 2) [setxy 226 (62.4 - (3.5 * (2 - temporal)))]
      ]
    ]
  ]


  ask machine 189 [                                                                            ; MACHINE 4
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 161 and ycor = [ycor] of sensor 161][

        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
        if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 2
        if (temporal > 198) [setxy 188 (28 + (3.5 * (200 -  temporal)))]
        if (temporal <= 198 and temporal >= 2) [setxy 188 35]
        if (temporal < 2) [setxy 188 (35 - (3.5 * (2 -  temporal)))]
      ]
    ]
  ]

  ask machine 190 [                                                                            ; MACHINE 5
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 162 and ycor = [ycor] of sensor 162][

        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
        if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 2
        if (temporal > 198) [setxy 110 (28 + (3.5 * (200 -  temporal)))]
        if (temporal <= 198 and temporal >= 1) [setxy 110 35]
        if (temporal < 2) [setxy 110 (35 - (3.5 * (2 -  temporal)))]
      ]
    ]
  ]

   ask machine 191 [                                                                            ; MACHINE 6
   ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 163 and ycor = [ycor] of sensor 163][

        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1)   "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
        if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
      ]
    ][
       if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 2
        if (temporal > 598) [setxy 28.5 (28 + (3.5 * (600 - temporal)))]
        if (temporal <= 598 and temporal >= 2) [setxy 28.5 35]
        if (temporal < 2) [setxy 28.5 (35 - (3.5 * (2 -  temporal)))]
      ]
    ]
  ]

  ask machine 192 [                                                                            ; MACHINE 7
    ifelse(Next.Completion <= Simulated.Time) [
      let Machine.which.completed Machine.Name
      set Machine.state "Idle"
      set Next.Completion 100000000
      ask products with [xcor = [xcor] of sensor 164 and ycor = [ycor] of sensor 164][
        EventMachineExit who [who] of machines with [Machine.Name = Machine.which.completed]
        set Machine.Used lput Machine.which.completed Machine.Used
        set Next.Product.status 1
        set currentsequenceorder currentsequenceorder + 1
        set Next.Product.Completion.Time ""
        set ProductRealCompletion lput (precision Simulated.Time 4) ProductRealCompletion
        set product.state "Waiting"
        if(Product-Label? = true)[set label (word (first label) "(" (precision (100 * (currentsequenceorder / ((length ProductOperations) - 1))) 1) "%)")]
        set Next.product.operation item currentsequenceorder ProductOperations

        if (Reactivity.Rule = "Rule 1 - Random Machine") [set Heading.Workstation one-of (item ((read-from-string (last Next.product.operation)) - 1) operations)]
        if (Reactivity.Rule = "Rule 2 - Nearest Machine") [
            let MinimumDistance min (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations)
            let MinimumPosition (position (MinimumDistance) (map [i -> precision (distance (one-of machines with [Machine.Name = i])) 2] item ((read-from-string (last Next.product.operation)) - 1) operations))
            set Heading.Workstation item MinimumPosition (item ((read-from-string (last Next.product.operation)) - 1) operations)
          ]
        if (Reactivity.Rule = "Rule 3 - Potential Fields") [

            let machines.possible (item ((read-from-string (last Next.product.operation)) - 1) operations)
            let next map [i -> item 0 [machine.atractiveness] of machines with [label = i]] machines.possible
            let next2[]
            let counter 0
            repeat length machines.possible [
              set next2 lput (item counter next / (item ((read-from-string (last item counter machines.possible)) - 1) (item ((read-from-string (last Machine.which.completed)) - 1) distances))) next2
              set counter counter + 1
            ]
            set Heading.Workstation item position max next2 next2 machines.possible
          ]
        ifelse (currentsequenceorder = length ProductOperations - 1) [set shape (word (conversion ProductType) ".f-product-" (minuscule producttype))][set shape (word (conversion ProductType) "." (currentsequenceorder - 1) "-product-" (minuscule producttype))]
      ]
    ][
      if(Machine.state = "Machine.Processing") [
        let temporal ""
        set temporal precision (Next.Completion - Simulated.Time) 2
        if (temporal > 198) [setxy 28.5 (117 - (3.5 * (200 - temporal)))]
        if (temporal <= 198 and temporal >= 2) [setxy 28.5 110]
        if (temporal < 2) [setxy 28.5 (110 + (3.5 * (2 -  temporal)))]
      ]
    ]
  ]

end

to PotentialFields

  ask machine 186 [set Products.Queue [self] of products with [xcor >= 90 and xcor <= 110 and ycor >= 97 and ycor <= 110 and heading.workstation = "M1"]]
  ask machine 187 [set Products.Queue [self] of products with [xcor >= 175 and xcor <= 190 and ycor >= 97 and ycor <= 110 and heading.workstation = "M2"]]
  ask machine 188 [set Products.Queue [self] of products with [xcor >= 230 and xcor <= 250 and ycor >= 63 and ycor <= 74 and heading.workstation = "M3"]]
  ask machine 189 [set Products.Queue [self] of products with [xcor >= 191 and xcor <= 208 and ycor >= 34 and ycor <= 49 and heading.workstation = "M4"]]
  ask machine 190 [set Products.Queue [self] of products with [xcor >= 115 and xcor <= 130 and ycor >= 34 and ycor <= 49 and heading.workstation = "M5"]]
  ask machine 191 [set Products.Queue [self] of products with [xcor >= 31 and xcor <= 53 and ycor >= 34 and ycor <= 49 and heading.workstation = "M6"]]
  ask machine 192 [set Products.Queue [self] of products with [xcor >= 5 and xcor <= 24 and ycor >= 97 and ycor <= 110 and heading.workstation = "M7"]]

  let A 0
  ask machines [
    set A 0
    set A sum (map [i -> item (position ([next.product.operation] of i) machine.operations.type) machine.operations.time] Products.Queue)
    ifelse (next.completion = 100000000) [
      set Machine.Atractiveness precision (1000000 / 1) 6
    ][
      set Machine.Atractiveness precision (1000000 / (1 + A + (next.completion - Simulated.Time))) 6
    ]
  ]


end


to intermediate.node [#1 #2]

  if ([xcor] of node #1 = [xcor] of node #2)[
    if ([ycor] of node #1 < [ycor] of node #2)[
      let temp (ceiling ([ycor] of node #1 / 5))* 5
      while [temp < [ycor] of node #2][
      print (word [xcor] of node #1 " " temp)
      set temp temp + 5
      ]
    ]
    if ([ycor] of node #1 > [ycor] of node #2)[
      let temp (ceiling ([ycor] of node #2 / 5))* 5
      while [temp < [ycor] of node #1][
      print (word [xcor] of node #1 " " temp)
      set temp temp + 5
      ]
    ]
  ]

  if ([ycor] of node #1 = [ycor] of node #2)[
      if ([xcor] of node #1 < [xcor] of node #2)[
      let temp (ceiling ([xcor] of node #1 / 5)) * 5
      while [temp < [xcor] of node #2][
      print (word temp " " [ycor] of node #1)
      set temp temp + 5
      ]
    ]
    if ([xcor] of node #1 > [xcor] of node #2)[
      let temp (ceiling ([xcor] of node #2 / 5)) * 5
      while [temp < [xcor] of node #1][
      print (word temp " " [ycor] of node #1)
      set temp temp + 5
      ]
    ]
  ]


end


to Product.Movement

  Cheking.Machine.Completion


  set simulated.time precision (simulated.time + 0.31) 2

   ask products [
    let product.ahead count products  in-cone 10 50
    if (product.state = "Movement" and product.ahead <= 1)[
      let distance-location distance Next.Node
      ifelse (distance-location > 0.4)[
        if ([shape] of conveyor [who] of Last.Node [who] of Next.Node = "default") [jump (0.300 * speed-factor) setxy (precision xcor 3) (precision ycor 3)]
        if ([shape] of conveyor [who] of Last.Node [who] of Next.Node = "curve1") [Curved.Move 2.400 4 "curve1" setxy (precision xcor 3) (precision ycor 3)]
        if ([shape] of conveyor [who] of Last.Node [who] of Next.Node = "curve2") [Curved.Move 2.149 8 "curve2" setxy (precision xcor 3) (precision ycor 3)]
        if ([shape] of conveyor [who] of Last.Node [who] of Next.Node = "curve3") [Curved.Move 2.149 8 "curve3" setxy (precision xcor 3) (precision ycor 3)]
      ][
        move-to Next.Node
        set Last.Node Next.Node
        set Next.Node [Addressed.To.Node] of Next.Node
        face Next.Node
      ]
    ]
  ]



  check-movement-W1
  check-movement-W6
  check-movement-W9
  check-movement-W16

  check-movement-W7
  check-movement-W8

  check-movement-W14
  check-movement-W15

  check-movement-W17
  check-movement-W18

  check-movement-W4
  check-movement-W5

  check-movement-W10
  check-movement-W11

  check-movement-W2
  check-movement-W3A
  check-movement-W3B

  check-movement-W12
  check-movement-W13



end

to check-movement-W9

  ; capturing sensors info
  ask sensor 138 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 138 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 139 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 139 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 141 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 141 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W9-Indicator = 0)[
    if (([Signal] of sensor 138 = 1) and ([Signal] of sensor 139 = 0) and ([Signal] of sensor 141 = 0)) [
      ask products with [xcor = [xcor] of sensor 138 and ycor = [ycor] of sensor 138] [set W9-Indicator 1 ifelse (Heading.Workstation = "M2") [Change.Gates.positions 7 8 40 8 Change.Gates.positions 9 10 9 16] [Change.Gates.positions 7 8 40 8 Change.Gates.positions 9 16 9 10] set product.state "Movement" ]
    ]
    if (([Signal] of sensor 138 = 0) and ([Signal] of sensor 139 = 1) and ([Signal] of sensor 141 = 0)) [
      ask products with [xcor = [xcor] of sensor 139 and ycor = [ycor] of sensor 139] [set W9-Indicator 1 ifelse (Heading.Workstation = "M2") [Change.Gates.positions 40 8 7 8 Change.Gates.positions 9 10 9 16][Change.Gates.positions 40 8 7 8 Change.Gates.positions 9 16 9 10]   set product.state "Movement" ]
    ]
    if (([Signal] of sensor 138 = 1) and ([Signal] of sensor 139 = 1) and ([Signal] of sensor 141 = 0)) [
      ask products with [xcor = [xcor] of sensor 138 and ycor = [ycor] of sensor 138] [set W9-Indicator 1 ifelse (Heading.Workstation = "M2") [Change.Gates.positions 7 8 40 8 Change.Gates.positions 9 10 9 16] [Change.Gates.positions 7 8 40 8 Change.Gates.positions 9 16 9 10] set product.state "Movement" ]
      ask products with [xcor = [xcor] of sensor 139 and ycor = [ycor] of sensor 139] [set product.state "Waiting"]
    ]
    if ([Signal] of sensor 141 = 1) [
      if ([Signal] of sensor 138 = 1) [
        Change.Gates.positions 7 8 40 8 Change.Gates.positions 9 16 9 10
        ask products with [xcor = [xcor] of sensor 138 and ycor = [ycor] of sensor 138] [set W9-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 139 = 1) [
        Change.Gates.positions 40 8 7 8  Change.Gates.positions 9 16 9 10
        ask products with [xcor = [xcor] of sensor 139 and ycor = [ycor] of sensor 139] [set W9-Indicator 1 set product.state "Movement"]
      ]
    ]
  ]
  ; Checking exit from segment
  ask sensor 140 [
    ask products in-radius 0.25 [set W9-Indicator 0 ]
  ]
  ask sensor 142 [
    ask products in-radius 0.25 [set W9-Indicator 0 ]
  ]

end

to check-movement-W1

  ; capturing sensors info
  ask sensor 143 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 143 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 144 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 144 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 146 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 146 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W1-Indicator = 0)[
    if (([Signal] of sensor 143 = 1) and ([Signal] of sensor 144 = 0) and ([Signal] of sensor 146 = 0)) [
      ask products with [xcor = [xcor] of sensor 143 and ycor = [ycor] of sensor 143] [set W1-Indicator 1 ifelse (Heading.Workstation = "M6") [Change.Gates.positions 60 63 61 63 Change.Gates.positions 64 65 64 71] [Change.Gates.positions 60 63 61 63 Change.Gates.positions 64 71 64 65] set product.state "Movement" ]
    ]
    if (([Signal] of sensor 143 = 0) and ([Signal] of sensor 144 = 1) and ([Signal] of sensor 146 = 0)) [
      ask products with [xcor = [xcor] of sensor 144 and ycor = [ycor] of sensor 144] [set W1-Indicator 1 ifelse (Heading.Workstation = "M6") [Change.Gates.positions 61 63 60 63 Change.Gates.positions 64 65 64 71][Change.Gates.positions 61 63 60 63 Change.Gates.positions 64 71 64 65]  set product.state "Movement" ]
    ]
    if (([Signal] of sensor 143 = 1) and ([Signal] of sensor 144 = 1) and ([Signal] of sensor 146 = 0)) [
      ask products with [xcor = [xcor] of sensor 143 and ycor = [ycor] of sensor 143] [set W1-Indicator 1 ifelse (Heading.Workstation = "M6") [Change.Gates.positions 60 63 61 63 Change.Gates.positions 64 65 64 71] [Change.Gates.positions 60 63 61 63 Change.Gates.positions 64 71 64 65] set product.state "Movement" ]
      ask products with [xcor = [xcor] of sensor 144 and ycor = [ycor] of sensor 144] [set product.state "Waiting"]
    ]
    if ([Signal] of sensor 146 = 1) [
      if ([Signal] of sensor 143 = 1) [
        Change.Gates.positions 60 63 61 63 Change.Gates.positions 64 71 64 65
        ask products with [xcor = [xcor] of sensor 143 and ycor = [ycor] of sensor 143] [set W1-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 144 = 1) [
        Change.Gates.positions 61 63 60 63  Change.Gates.positions 64 71 64 65
        ask products with [xcor = [xcor] of sensor 144 and ycor = [ycor] of sensor 144] [set W1-Indicator 1 set product.state "Movement"]
      ]

    ]
  ]
  ; Checking exit from segment
  ask sensor 145 [
    ask products in-radius 0.25 [set W1-Indicator 0 ]
  ]
  ask sensor 147 [
    ask products in-radius 0.25 [set W1-Indicator 0 ]
  ]

end

to check-movement-W6

  ; capturing sensors info
  ask sensor 148 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 148 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 149 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 149 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 151 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 151 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W6-Indicator = 0)[
    if (([Signal] of sensor 148 = 1) and ([Signal] of sensor 149 = 0) and ([Signal] of sensor 151 = 0)) [
      ask products with [xcor = [xcor] of sensor 148 and ycor = [ycor] of sensor 148] [set W6-Indicator 1 ifelse (Heading.Workstation = "M1") [Change.Gates.positions 86 87 58 87 Change.Gates.positions 88 91 88 89] [Change.Gates.positions 86 87 58 87 Change.Gates.positions 88 89 88 91] set product.state "Movement" ]
    ]
    if (([Signal] of sensor 148 = 0) and ([Signal] of sensor 149 = 1) and ([Signal] of sensor 151 = 0)) [
      ask products with [xcor = [xcor] of sensor 149 and ycor = [ycor] of sensor 149] [set W6-Indicator 1 ifelse (Heading.Workstation = "M1") [Change.Gates.positions 58 87 86 87 Change.Gates.positions 88 91 88 89][Change.Gates.positions 58 87 86 87 Change.Gates.positions 88 89 88 91]   set product.state "Movement" ]
    ]
    if (([Signal] of sensor 148 = 1) and ([Signal] of sensor 149 = 1) and ([Signal] of sensor 151 = 0)) [
      ask products with [xcor = [xcor] of sensor 148 and ycor = [ycor] of sensor 148] [set W6-Indicator 1 ifelse (Heading.Workstation = "M1") [Change.Gates.positions 86 87 58 87 Change.Gates.positions 88 91 88 89] [Change.Gates.positions 86 87 58 87 Change.Gates.positions 88 89 88 91] set product.state "Movement" ]
      ask products with [xcor = [xcor] of sensor 149 and ycor = [ycor] of sensor 149] [set product.state "Waiting"]
    ]
    if ([Signal] of sensor 151 = 1) [
      if ([Signal] of sensor 148 = 1) [
        Change.Gates.positions 86 87 58 87 Change.Gates.positions 88 89 88 91
        ask products with [xcor = [xcor] of sensor 148 and ycor = [ycor] of sensor 148] [set W6-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 149 = 1) [
        Change.Gates.positions 58 87 86 87 Change.Gates.positions 88 89 88 91
        ask products with [xcor = [xcor] of sensor 149 and ycor = [ycor] of sensor 149] [set W6-Indicator 1 set product.state "Movement"]
      ]
    ]
  ]
  ; Checking exit from segment
  ask sensor 150 [
    ask products in-radius 0.25 [set W6-Indicator 0 ]
  ]
  ask sensor 152 [
    ask products in-radius 0.25 [set W6-Indicator 0 ]
  ]

end

to check-movement-W16

  ; capturing sensors info
  ask sensor 153 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 153 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 154 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 154 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 156 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 156 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W16-Indicator = 0)[
    if (([Signal] of sensor 153 = 1) and ([Signal] of sensor 154 = 0) and ([Signal] of sensor 156 = 0)) [
      ask products with [xcor = [xcor] of sensor 153 and ycor = [ycor] of sensor 153] [set W16-Indicator 1 ifelse (Heading.Workstation = "M5") [Change.Gates.positions 42 45 43 45 Change.Gates.positions 46 47 46 53] [Change.Gates.positions 42 45 43 45 Change.Gates.positions  46 53 46 47] set product.state "Movement" ]
    ]
    if (([Signal] of sensor 153 = 0) and ([Signal] of sensor 154 = 1) and ([Signal] of sensor 156 = 0)) [
      ask products with [xcor = [xcor] of sensor 154 and ycor = [ycor] of sensor 154] [set W16-Indicator 1 ifelse (Heading.Workstation = "M5") [Change.Gates.positions  43 45 42 45 Change.Gates.positions 46 47 46 53][Change.Gates.positions 43 45 42 45 Change.Gates.positions 46 53 46 47]  set product.state "Movement" ]
    ]
    if (([Signal] of sensor 153 = 1) and ([Signal] of sensor 154 = 1) and ([Signal] of sensor 156 = 0)) [
      ask products with [xcor = [xcor] of sensor 153 and ycor = [ycor] of sensor 153] [
        set W16-Indicator 1
        ifelse (Heading.Workstation = "M5") [Change.Gates.positions 42 45 43 45 Change.Gates.positions 46 47 46 53] [Change.Gates.positions 42 45 43 45 Change.Gates.positions  46 53 46 47]
      ]
      ask products with [xcor = [xcor] of sensor 154 and ycor = [ycor] of sensor 154] [set product.state "Waiting"]
    ]
    if ([Signal] of sensor 156 = 1) [
      if ([Signal] of sensor 153 = 1) [
        Change.Gates.positions 42 45 43 45 Change.Gates.positions 46 53 46 47
        ask products with [xcor = [xcor] of sensor 153 and ycor = [ycor] of sensor 153] [set W16-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 154 = 1) [
        Change.Gates.positions 43 45 42 45  Change.Gates.positions 46 53 46 47
        ask products with [xcor = [xcor] of sensor 154 and ycor = [ycor] of sensor 154] [set W16-Indicator 1 set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 153 = 1) and ([Signal] of sensor 154 = 1)) [   ; Cambio solo a esta salida
      ask products with [xcor = [xcor] of sensor 154 and ycor = [ycor] of sensor 154] [set W16-Indicator 1 ifelse (Heading.Workstation = "M5") [Change.Gates.positions  43 45 42 45 Change.Gates.positions 46 47 46 53][Change.Gates.positions 43 45 42 45 Change.Gates.positions 46 53 46 47]  set product.state "Movement" ]
    ]

  ]
  ; Checking exit from segment
  ask sensor 155 [
    ask products in-radius 0.25 [set W16-Indicator 0 ]
  ]
  ask sensor 157 [
    ask products in-radius 0.25 [set W16-Indicator 0 ]
  ]

end

to check-movement-W7

  ; capturing sensors info

  ask sensor 151 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 151 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 158 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 158
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 186 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

  ; Checking condition

    if (([Signal] of sensor 151 = 1) and ([Signal] of sensor 158 = 0))[
      ask products with [xcor = [xcor] of sensor 151 and ycor = [ycor] of sensor 151] [
        set W7-Indicator 1 set product.state "Movement"
      ]
    ]


  if(W7-Indicator = 1)[
    if (([Signal] of sensor 158 = 1))[
      ask products with [xcor = [xcor] of sensor 158 and ycor = [ycor] of sensor 158][
        if ((Heading.Workstation = "M1") and (([Machine.state] of machine 186) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 186 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]

          ]
        ]

      ]

    ]
  ]

  ask sensor 158 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M1" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 186) = "Idle"))[
        set W7-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W8

  ; capturing sensors info
  ask sensor 158 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 158
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 167 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 167 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 138 [                                                                                                               ;  Sensor next PLC
    let temp 0 ask products in-radius 0.20 [move-to sensor 138 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W8-Indicator = 0)[
    if (([Signal] of sensor 158 = 1) and ([Signal] of sensor 167 = 0) and ([Signal] of sensor 138 = 0)) [
      ask products with [xcor = [xcor] of sensor 158 and ycor = [ycor] of sensor 158 and heading.workstation != "M1" and heading.workstation != "Unknown"] [
        set W8-Indicator 1
        ifelse (Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4") [
          Change.Gates.positions 3 4 90 4 Change.Gates.positions 5 6 5 44
        ][
          Change.Gates.positions 3 4 90 4 Change.Gates.positions 5 44 5 6
        ]
        if ([machine.state] of machine 186 != "Machine.Processing" ) [set product.state "Movement"]

      ]
    ]
    if (([Signal] of sensor 158 = 0) and ([Signal] of sensor 167 = 1) and ([Signal] of sensor 138 = 0)) [
      ask products with [xcor = [xcor] of sensor 167 and ycor = [ycor] of sensor 167] [
        set W8-Indicator 1
        ifelse (Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4") [
          Change.Gates.positions 90 4 3 4  Change.Gates.positions 5 6 5 44
        ][
          Change.Gates.positions 90 4 3 4 Change.Gates.positions 5 44 5 6
        ]
        set product.state "Movement"
      ]
    ]
    if ([Signal] of sensor 138 = 1) [
      if ([Signal] of sensor 158 = 1) [
        Change.Gates.positions 3 4 90 4 Change.Gates.positions 5 44 5 6
        ask products with [xcor = [xcor] of sensor 158 and ycor = [ycor] of sensor 158 and product.state != "Waiting"] [set W8-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 167 = 1) [
        Change.Gates.positions 90 4 3 4  Change.Gates.positions 5 44 5 6
        ask products with [xcor = [xcor] of sensor 167 and ycor = [ycor] of sensor 167] [set W8-Indicator 1 set product.state "Movement"]
      ]
      if (W9-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 138 and ycor = [ycor] of sensor 138] [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 158 = 1) and ([Signal] of sensor 167 = 1)) [
      ask products with [xcor = [xcor] of sensor 167 and ycor = [ycor] of sensor 167] [
        set W8-Indicator 1
        ifelse (Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4") [
          Change.Gates.positions 90 4 3 4  Change.Gates.positions 5 6 5 44
        ][
          Change.Gates.positions 90 4 3 4 Change.Gates.positions 5 44 5 6
        ]
        set product.state "Movement"
      ]
    ]
  ]

  ; Checking exit from segment

  ask sensor 138 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W8-Indicator 0]
  ]
  ask sensor 168 [
    ask products in-radius 0.25 [set W8-Indicator 0]
  ]

end

to check-movement-W14

  ; capturing sensors info

  ask sensor 177 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 177 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 161 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 161
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 189 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

  ; Checking condition

    if (([Signal] of sensor 177 = 1) and ([Signal] of sensor 161 = 0))[
      ask products with [xcor = [xcor] of sensor 177 and ycor = [ycor] of sensor 177] [
        set W14-Indicator 1 set product.state "Movement"
      ]
    ]


  if(W14-Indicator = 1)[
    if (([Signal] of sensor 161 = 1))[
      ask products with [xcor = [xcor] of sensor 161 and ycor = [ycor] of sensor 161][
        if ((Heading.Workstation = "M4") and (([Machine.state] of machine 189) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 189 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]
          ]
        ]
      ]
    ]
  ]

  ask sensor 161 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M4" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 189) = "Idle"))[
        set W14-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W15

  ; capturing sensors info
  ask sensor 161 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 161
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 171 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 171 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 153 [                                                                                                               ;  Sensor next PLC
    let temp 0 ask products in-radius 0.20 [move-to sensor 153 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W15-Indicator = 0)[
    if (([Signal] of sensor 161 = 1) and ([Signal] of sensor 171 = 0) and ([Signal] of sensor 153 = 0)) [
      ask products with [xcor = [xcor] of sensor 161 and ycor = [ycor] of sensor 161 and heading.workstation != "M4" and heading.workstation != "Unknown"] [
        set W15-Indicator 1
        ifelse (Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1") [
          Change.Gates.positions 34 37 36 37 Change.Gates.positions 38 41 38 39
        ][
          Change.Gates.positions 34 37 36 37 Change.Gates.positions 38 39 38 41
        ]
        if ([machine.state] of machine 189 != "Machine.Processing" ) [set product.state "Movement"]

      ]
    ]
    if (([Signal] of sensor 161 = 0) and ([Signal] of sensor 171 = 1) and ([Signal] of sensor 153 = 0)) [
      ask products with [xcor = [xcor] of sensor 171 and ycor = [ycor] of sensor 171] [
        set W15-Indicator 1
        ifelse (Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1") [
          Change.Gates.positions  36 37 34 37 Change.Gates.positions 38 41 38 39
        ][
          Change.Gates.positions 36 37 34 37 Change.Gates.positions 38 39 38 41
        ]
        set product.state "Movement"
      ]
    ]
    if ([Signal] of sensor 153 = 1) [
      if ([Signal] of sensor 161 = 1) [
        Change.Gates.positions 36 37 34 37 Change.Gates.positions 38 39 38 41
        ask products with [xcor = [xcor] of sensor 161 and ycor = [ycor] of sensor 161 and product.state != "Waiting"] [set W15-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 171 = 1) [
        Change.Gates.positions 36 37 34 37  Change.Gates.positions 38 39 38 41
        ask products with [xcor = [xcor] of sensor 171 and ycor = [ycor] of sensor 171] [set W15-Indicator 1 set product.state "Movement"]
      ]
      if (W16-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 153 and ycor = [ycor] of sensor 153] [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 161 = 1) and ([Signal] of sensor 171 = 1)) [
      ask products with [xcor = [xcor] of sensor 171 and ycor = [ycor] of sensor 171] [
        set W15-Indicator 1
        ifelse (Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1") [
          Change.Gates.positions  36 37 34 37 Change.Gates.positions 38 41 38 39
        ][
          Change.Gates.positions 36 37 34 37 Change.Gates.positions 38 39 38 41
        ]
        set product.state "Movement"
      ]
    ]
  ]

  ; Checking exit from segment

  ask sensor 153 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W15-Indicator 0]
  ]
  ask sensor 172 [
    ask products in-radius 0.25 [set W15-Indicator 0]
  ]

end

to check-movement-W17

  ; capturing sensors info

  ask sensor 156 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 156 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 162 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 162
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 190 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

  ; Checking condition

    if (([Signal] of sensor 156 = 1) and ([Signal] of sensor 162 = 0))[
      ask products with [xcor = [xcor] of sensor 156 and ycor = [ycor] of sensor 156] [
        set W17-Indicator 1 set product.state "Movement"
      ]
    ]


  if(W17-Indicator = 1)[
    if ([Signal] of sensor 162 = 1)[
      ask products with [xcor = [xcor] of sensor 162 and ycor = [ycor] of sensor 162][
        if ((Heading.Workstation = "M5") and (([Machine.state] of machine 190) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 190 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]

          ]
        ]
      ]
    ]
  ]

  ask sensor 162 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M5" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 190) = "Idle"))[
        set W17-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W18

  ; capturing sensors info
  ask sensor 162 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 162
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 173 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 173 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 143 [                                                                                                               ;  Sensor next PLC
    let temp 0 ask products in-radius 0.20 [move-to sensor 143 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W18-Indicator = 0)[
    if (([Signal] of sensor 162 = 1) and ([Signal] of sensor 173 = 0) and ([Signal] of sensor 143 = 0)) [
      ask products with [xcor = [xcor] of sensor 162 and ycor = [ycor] of sensor 162 and heading.workstation != "M5" and heading.workstation != "Unknown"] [
        set W18-Indicator 1
        ifelse (Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions 52 55 54 55 Change.Gates.positions 56 59 56 57
        ][
          Change.Gates.positions 52 55 54 55 Change.Gates.positions 56 57 56 59
        ]
        if ([machine.state] of machine 190 != "Machine.Processing" ) [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 162 = 0) and ([Signal] of sensor 173 = 1) and ([Signal] of sensor 143 = 0)) [
      ask products with [xcor = [xcor] of sensor 173 and ycor = [ycor] of sensor 173] [
        set W18-Indicator 1
        ifelse (Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions  54 55 52 55  Change.Gates.positions 56 59 56 57
        ][
          Change.Gates.positions 54 55 52 55 Change.Gates.positions 56 57 56 59
        ]
        set product.state "Movement"
      ]
    ]
    if ([Signal] of sensor 143 = 1) [
      if ([Signal] of sensor 162 = 1) [
        Change.Gates.positions 52 55 54 55 Change.Gates.positions 56 57 56 59
        ask products with [xcor = [xcor] of sensor 162 and ycor = [ycor] of sensor 162 and product.state != "Waiting"] [set W18-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 173 = 1) [
        Change.Gates.positions 54 55 52 55  Change.Gates.positions 56 57 56 59
        ask products with [xcor = [xcor] of sensor 173 and ycor = [ycor] of sensor 173] [set W18-Indicator 1 set product.state "Movement"]
      ]
      if (W1-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 143 and ycor = [ycor] of sensor 143] [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 162 = 1) and ([Signal] of sensor 173 = 1)) [
      ask products with [xcor = [xcor] of sensor 173 and ycor = [ycor] of sensor 173] [
        set W18-Indicator 1
        ifelse (Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions  54 55 52 55  Change.Gates.positions 56 59 56 57
        ][
          Change.Gates.positions 54 55 52 55 Change.Gates.positions 56 57 56 59
        ]
        set product.state "Movement"
      ]
    ]
  ]

  ; Checking exit from segment

  ask sensor 143 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W18-Indicator 0]
  ]
  ask sensor 174 [
    ask products in-radius 0.25 [set W18-Indicator 0]
  ]

end

to check-movement-W4

  ; capturing sensors info

  ask sensor 184 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 184 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 164 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 164
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 192 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

  ; Checking condition

  if(W4-Indicator = 1)[
    if (([Signal] of sensor 164 = 1))[
      ask products with [xcor = [xcor] of sensor 164 and ycor = [ycor] of sensor 164][
        if ((Heading.Workstation = "M7") and (([Machine.state] of machine 192) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4)ProductRealStart
          let WhichProduct who
          ask machine 192 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]

          ]
        ]

      ]
    ]
  ]

  if (([Signal] of sensor 184 = 1) and ([Signal] of sensor 164 = 0))[
    ask products with [xcor = [xcor] of sensor 184 and ycor = [ycor] of sensor 184] [
      set W4-Indicator 1 set product.state "Movement"
    ]
  ]

  ask sensor 164 [                                            ; sensor need to be free
    ask products in-radius 0.20 [
      if ((Heading.Workstation != "M7" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 192) = "Idle"))[
        set W4-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W5

  ; capturing sensors info
  ask sensor 164 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.25 [
      move-to sensor 164
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 165 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 165 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 148 [                                                                                                               ;  Sensor next PLC
    let temp 0 ask products in-radius 0.20 [move-to sensor 148 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W5-Indicator = 0)[
    if (([Signal] of sensor 164 = 1) and ([Signal] of sensor 165 = 0) and ([Signal] of sensor 148 = 0)) [
      ask products with [xcor = [xcor] of sensor 164 and ycor = [ycor] of sensor 164 and heading.workstation != "M7" and heading.workstation != "Unknown"] [
        set W5-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions 80 83 82 83 Change.Gates.positions 84 85 84 62
        ][
          Change.Gates.positions 80 83 82 83 Change.Gates.positions 84 62 84 85
        ]
        if ([machine.state] of machine 192 != "Machine.Processing" ) [set product.state "Movement"]

      ]
    ]
    if (([Signal] of sensor 164 = 0) and ([Signal] of sensor 165 = 1) and ([Signal] of sensor 148 = 0)) [
      ask products with [xcor = [xcor] of sensor 165 and ycor = [ycor] of sensor 165] [
        set W5-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions 82 83 80 83 Change.Gates.positions 84 85 84 62
        ][
          Change.Gates.positions 82 83 80 83 Change.Gates.positions 84 62 84 85
        ]
        set product.state "Movement"
      ]
    ]
    if ([Signal] of sensor 148 = 1) [
      if ([Signal] of sensor 164 = 1) [
        Change.Gates.positions 80 83 82 83  Change.Gates.positions 84 62 84 85
        ask products with [xcor = [xcor] of sensor 164 and ycor = [ycor] of sensor 164 and product.state != "Waiting"] [set W5-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 165 = 1) [
        Change.Gates.positions 82 83 80 83   Change.Gates.positions 84 62 84 85
        ask products with [xcor = [xcor] of sensor 165 and ycor = [ycor] of sensor 165] [set W5-Indicator 1 set product.state "Movement"]
      ]
      if (W6-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 148 and ycor = [ycor] of sensor 148] [set product.state "Movement"]
      ]

    ]
    if (([Signal] of sensor 164 = 1) and ([Signal] of sensor 165 = 1)) [
      ask products with [xcor = [xcor] of sensor 165 and ycor = [ycor] of sensor 165] [
        set W5-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions 82 83 80 83 Change.Gates.positions 84 85 84 62
        ][
          Change.Gates.positions 82 83 80 83 Change.Gates.positions 84 62 84 85
        ]
        set product.state "Movement"
      ]
    ]
  ]

  ; Checking exit from segment

  ask sensor 148 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W5-Indicator 0]
  ]
  ask sensor 166 [
    ask products in-radius 0.25 [set W5-Indicator 0]
  ]

end

to check-movement-W10

  ; capturing sensors info

  ask sensor 141 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 141 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 159 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 159
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]



  ; Checking condition

    if (([Signal] of sensor 141 = 1) and ([Signal] of sensor 159 = 0))[
      ask products with [xcor = [xcor] of sensor 141 and ycor = [ycor] of sensor 141] [
        set W10-Indicator 1 set product.state "Movement"
      ]
    ]


  if(W10-Indicator = 1)[
    if (([Signal] of sensor 159 = 1))[
      ask products with [xcor = [xcor] of sensor 159 and ycor = [ycor] of sensor 159][
        if ((Heading.Workstation = "M2") and (([Machine.state] of machine 187) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 187 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]

          ]
        ]

      ]
    ]
  ]

  ask sensor 159 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M2" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 187) = "Idle"))[
        set W10-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W11

  ; capturing sensors info
  ask sensor 159 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 159
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 169 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 169 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 175 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 175 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W11-Indicator = 0)[
    if (([Signal] of sensor 159 = 1) and ([Signal] of sensor 169 = 0) and ([Signal] of sensor 175 = 0)) [
      ask products with [xcor = [xcor] of sensor 159 and ycor = [ycor] of sensor 159 and heading.workstation != "M2" and heading.workstation != "Unknown"] [
        set W11-Indicator 1
        ifelse (Heading.Workstation = "M4" or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1") [
          Change.Gates.positions 15 18 17 18 Change.Gates.positions 19 25 19 20
        ][
          Change.Gates.positions 15 18 17 18 Change.Gates.positions 19 20 19 25
        ]
        if ([machine.state] of machine 187 != "Machine.Processing" ) [set product.state "Movement"]

      ]
    ]
    if (([Signal] of sensor 159 = 0) and ([Signal] of sensor 169 = 1) and ([Signal] of sensor 175 = 0)) [
      ask products with [xcor = [xcor] of sensor 169 and ycor = [ycor] of sensor 169] [
        set W11-Indicator 1
        ifelse (Heading.Workstation = "M4" or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1" or Heading.Workstation = "M2") [
          Change.Gates.positions 17 18 15 18   Change.Gates.positions 19 25 19 20
        ][
          Change.Gates.positions 17 18 15 18 Change.Gates.positions 19 20 19 25
        ]
        set product.state "Movement"
      ]
    ]
    if ([Signal] of sensor 175 = 1) [
      if ([Signal] of sensor 159 = 1 and ([Signal] of sensor 169 = 0)) [
        Change.Gates.positions 15 18 17 18 Change.Gates.positions 19 25 19 20
        ask products with [xcor = [xcor] of sensor 159 and ycor = [ycor] of sensor 159 and product.state != "Waiting"] [set W11-Indicator 1 set product.state "Movement"] ;aqui
      ]
      if ([Signal] of sensor 159 = 0 and ([Signal] of sensor 169 = 1)) [
        Change.Gates.positions 17 18 15 18  Change.Gates.positions 19 25 19 20
        ask products with [xcor = [xcor] of sensor 169 and ycor = [ycor] of sensor 169] [set W11-Indicator 1 set product.state "Movement"]
      ]
      if (W12-Indicator = 1 and W13-Indicator = 0) [
        ask products with [xcor = [xcor] of sensor 175 and ycor = [ycor] of sensor 175] [set product.state "Movement"]
      ]
      if (W12-Indicator = 1 and W13-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 175 and ycor = [ycor] of sensor 175] [set product.state "Waiting"]
      ]
    ]

    if (([Signal] of sensor 159 = 1) and ([Signal] of sensor 169 = 1) and ([Signal] of sensor 175 = 0)) [
      ask products with [xcor = [xcor] of sensor 169 and ycor = [ycor] of sensor 169] [
        set W11-Indicator 1
        ifelse (Heading.Workstation = "M4" or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7" or Heading.Workstation = "M1" or Heading.Workstation = "M2") [
          Change.Gates.positions 17 18 15 18   Change.Gates.positions 19 25 19 20
        ][
          Change.Gates.positions 17 18 15 18 Change.Gates.positions 19 20 19 25
        ]
        set product.state "Movement"
      ]
    ]

  ]

  ; Checking exit from segment

  ask sensor 175 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W11-Indicator 0]
  ]
  ask sensor 170 [
    ask products in-radius 0.25 [set W11-Indicator 0]
  ]

end

to check-movement-W2

  ; capturing sensors info

  ask sensor 146 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 146 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 163 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 163
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 191 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

  ; Checking condition

    if (([Signal] of sensor 146 = 1) and ([Signal] of sensor 163 = 0))[
      ask products with [xcor = [xcor] of sensor 146 and ycor = [ycor] of sensor 146] [
        set W2-Indicator 1 set product.state "Movement"
      ]
    ]

    if (([Signal] of sensor 146 = 1) and ([Signal] of sensor 163 = 1))[
      ask products with [xcor = [xcor] of sensor 146 and ycor = [ycor] of sensor 146] [
        set W2-Indicator 1 set product.state "Waiting"
      ]
    ]


  if(W2-Indicator = 1)[
    if ([Signal] of sensor 163 = 1)[
      ask products with [xcor = [xcor] of sensor 163 and ycor = [ycor] of sensor 163][
        if ((Heading.Workstation = "M6") and (([Machine.state] of machine 191) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 191 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]

          ]
        ]

      ]
    ]
  ]

  ask sensor 163 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M6" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 191) = "Idle"))[
        set W2-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W3A

  ; capturing sensors info
  ask sensor 163 [                                                                                                               ; Machine Sensor posible check of completion
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 163
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]
  ask sensor 180 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 180 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W3A-Indicator = 0)[
    if (([Signal] of sensor 163 = 1) and ([Signal] of sensor 180 = 0)) [
      ask products with [xcor = [xcor] of sensor 163 and ycor = [ycor] of sensor 163 and heading.workstation != "M6" and heading.workstation != "Unknown"] [
        set W3A-Indicator 1
        ifelse (Heading.Workstation = "M7" or Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions  70 73 72 73
        ][
          Change.Gates.positions 70 73 72 73                                        ; It is the same. It is just in case.
        ]
        if ([machine.state] of machine 191 != "Machine.Processing" ) [set product.state "Movement"]

      ]
    ]
    if (([Signal] of sensor 163 = 0) and ([Signal] of sensor 180 = 1)) [
      ask products with [xcor = [xcor] of sensor 180 and ycor = [ycor] of sensor 180] [
        set W3A-Indicator 1
        ifelse (Heading.Workstation = "M7" or Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions 72 73 70 73
        ][
          Change.Gates.positions 72 73 70 73
        ]
        set product.state "Movement"
      ]
    ]
    if (([Signal] of sensor 163 = 1) and ([Signal] of sensor 180 = 1)) [
      ask products with [xcor = [xcor] of sensor 180 and ycor = [ycor] of sensor 180] [
        set W3A-Indicator 1
        ifelse (Heading.Workstation = "M7" or Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3" or Heading.Workstation = "M4" or Heading.Workstation = "M5") [
          Change.Gates.positions 72 73 70 73
        ][
          Change.Gates.positions 72 73 70 73
        ]
        set product.state "Movement"
      ]
    ]

  ]

  ; Checking exit from segment

  ask sensor 181 [                                            ; sensor need to be free
    ask products in-radius 0.25 [set W3A-Indicator 0]
  ]

end

to check-movement-W3B

  ; capturing sensors info
  ask sensor 182 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 182 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 184 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 184 set Product.State "Waiting" set temp 1] set signal temp
  ]



  if (W3B-Indicator = 1) [
    if (([Signal] of sensor 184 = 1) and([Signal] of sensor 164 = 0))[
      ask products with [xcor = [xcor] of sensor 184 and ycor = [ycor] of sensor 184][
         set product.state "Movement" set W3B-Indicator 0
      ]
    ]
  ]


  if (W3B-Indicator = 0)[
    if (([Signal] of sensor 182 = 1) and([Signal] of sensor 184 = 0)) [
      ask products with [xcor = [xcor] of sensor 182 and ycor = [ycor] of sensor 182] [
        set W3B-Indicator 1
        ifelse (Heading.Workstation = "M7") [
          Change.Gates.positions 74 75 74 81
        ][
          Change.Gates.positions 74 81 74 75
        ]
        set product.state "Movement" ]
    ]
    if ([Signal] of sensor 184 = 1) [
      if ([Signal] of sensor 182 = 1) [
        Change.Gates.positions 74 81 74 75
        ask products with [xcor = [xcor] of sensor 182 and ycor = [ycor] of sensor 182] [set W3B-Indicator 1 set product.state "Movement"]
      ]
      if (W4-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 184 and ycor = [ycor] of sensor 184] [set product.state "Movement"]
      ]
    ]
  ]
  ; Checking exit from segment
  ask sensor 183 [
    ask products in-radius 0.25 [set W3B-Indicator 0 ]
  ]
  ask sensor 185 [
    ask products in-radius 0.25 [set W3B-Indicator 0 ]
  ]

end

to check-movement-W12

  ; capturing sensors info

  ask sensor 176 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 176 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 160 [
    let temp 0 ask products in-radius 0.20 [
      move-to sensor 160
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1
    ]
    set signal temp
  ]

  ask machine 188 [                                                                                       ; Ask machine if finished (Completed) or not
    ; Machine.Signal
  ]

    if (([Signal] of sensor 176 = 1) and ([Signal] of sensor 160 = 0))[
      ask products with [xcor = [xcor] of sensor 176 and ycor = [ycor] of sensor 176] [
        set W12-Indicator 1 set product.state "Movement"
      ]
    ]

  ;;; Linea Anterior///   if (([Signal] of sensor 160 = 1)) [ ; if (([Signal] of sensor 176 = 0) and ([Signal] of sensor 160 = 1))[ AQUI
  if(W12-Indicator = 1)[

    if ((([Signal] of sensor 160 = 1))) [ ; and ([Signal] of sensor 175 = 0) and ([Signal] of sensor 178 = 0))[
      ask products with [xcor = [xcor] of sensor 160 and ycor = [ycor] of sensor 160][
        if ((Heading.Workstation = "M3") and (([Machine.state] of machine 188) = "Idle"))[
          let Operation.To.Process.Temp ""
          set product.state "Processing.Product"
          set Operation.To.Process.Temp Next.Product.Operation                                            ; POSIBLE LUGAR PARA ACUALIZAR NEXT
          set ProductRealStart lput (precision Simulated.Time 4) ProductRealStart
          let WhichProduct who
          ask machine 188 [
            EventMachineEntry WhichProduct who
            set Machine.state "Machine.Processing"
            let Operation.Temp.Position (position Operation.To.Process.Temp Machine.Operations.Type)
            if (Modeling.Type = "Deterministic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time)]     ; Aqui se pone la duracion del procesamiento.
            if (Modeling.Type = "Stochastic") [set Next.Completion Simulated.Time + (item Operation.Temp.Position Machine.Operations.Time) + precision (random-exponential 10) 2]

          ]
        ]

      ]
    ]




  ]

  ask sensor 160 [                                            ; sensor need to be free
    ask products in-radius 0.25 [
      if ((Heading.Workstation != "M3" or Heading.Workstation = "Unknown") and (([Machine.state] of machine 188) = "Idle"))[
        set W12-Indicator 0]
        set product.state "Movement"
      ]
  ]

end

to check-movement-W13

  ; capturing sensors info
  ask sensor 175 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 175 set Product.State "Waiting" set temp 1] set signal temp
  ]
  ask sensor 160 [
    let temp 0
    ask products in-radius 0.20 [
      move-to sensor 160
      ifelse (Product.State = "Processing.Product") [set Product.State "Processing.Product"][set Product.State "Waiting"]
      set temp 1]
    set signal temp
  ]
  ask sensor 177 [
    let temp 0 ask products in-radius 0.20 [move-to sensor 177 set Product.State "Waiting" set temp 1] set signal temp
  ]

  ; Checking condition and setting gates  (Missing condition 1,1,1 and 1,1,0 due to are unlikely to happen)

  if (W13-Indicator = 0)[
    if (([Signal] of sensor 160 = 1) and ([Signal] of sensor 175 = 0) and ([Signal] of sensor 177 = 0)) [
      ask products with [xcor = [xcor] of sensor 160 and ycor = [ycor] of sensor 160 and heading.workstation != "M3" and heading.workstation != "Unknown"] [
        set W13-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3"  or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions 24 27 26 27 Change.Gates.positions  28 35 28 29
      ] [
          Change.Gates.positions 24 27 26 27 Change.Gates.positions  28 29 28 35
        ]
        if ([machine.state] of machine 188 != "Machine.Processing" ) [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 160 = 0) and ([Signal] of sensor 175 = 1) and ([Signal] of sensor 177 = 0)) [
      ask products with [xcor = [xcor] of sensor 175 and ycor = [ycor] of sensor 175] [
        set W13-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3"  or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions 26 27 24 27 Change.Gates.positions 28 35 28 29
        ][
          Change.Gates.positions 26 27 24 27 Change.Gates.positions  28 29 28 35
        ]
        set product.state "Movement"
      ]
    ]


    if ([Signal] of sensor 177 = 1) [
      if ([Signal] of sensor 160 = 1) [
        Change.Gates.positions 26 27 24 27  Change.Gates.positions 28 35 28 29
        ask products with [xcor = [xcor] of sensor 160 and ycor = [ycor] of sensor 160 and product.state != "Waiting"] [set W13-Indicator 1 set product.state "Movement"]
      ]
      if ([Signal] of sensor 175 = 1) [
        Change.Gates.positions 24 27 26 27   Change.Gates.positions 28 35 28 29
        ask products with [xcor = [xcor] of sensor 175 and ycor = [ycor] of sensor 175] [set W13-Indicator 1 set product.state "Movement"]
      ]
      if (W14-Indicator = 1) [
        ask products with [xcor = [xcor] of sensor 177 and ycor = [ycor] of sensor 177] [set product.state "Movement"]
      ]
    ]
    if (([Signal] of sensor 160 = 1) and ([Signal] of sensor 175 = 1)) [
      ask products with [xcor = [xcor] of sensor 175 and ycor = [ycor] of sensor 175] [
        set W13-Indicator 1
        ifelse (Heading.Workstation = "M1" or Heading.Workstation = "M2" or Heading.Workstation = "M3"  or Heading.Workstation = "M5" or Heading.Workstation = "M6" or Heading.Workstation = "M7") [
          Change.Gates.positions 26 27 24 27 Change.Gates.positions 28 35 28 29
        ][
          Change.Gates.positions 26 27 24 27 Change.Gates.positions  28 29 28 35
        ]
        set product.state "Movement"
      ]
    ]
  ]

  ; Checking exit from segment
  ask sensor 178 [
    ask products in-radius 0.25 [set W13-Indicator 0 ]
  ]
  ask sensor 179 [
    ask products in-radius 0.25 [set W13-Indicator 0 ]
  ]

end

to-report distance-link [#1 #2]
  report sum [distancexy #1 #2] of both-ends - link-length
end

to Moving.Product

  if (mouse-down? and mouse-aux = 0) [
    ask products [if(distancexy mouse-xcor mouse-ycor <= 10) [set Mouse-Aux who set Product.State "Mouse-Moving"]]
  ]
  if (mouse-down? and mouse-aux != 0) [
    ask product mouse-aux [setxy mouse-xcor mouse-ycor]
  ]



  if (not mouse-down? and mouse-aux != 0) [
    ask min-one-of links [distance-link mouse-xcor mouse-ycor][
      let aux-x mouse-xcor
      let aux-y mouse-ycor
      let tempx-end1 [xcor] of end1
      let tempx-end2 [xcor] of end2
      let tempy-end1 [ycor] of end1
      let tempy-end2 [ycor] of end2
      let link-heading-direction link-heading
      let next.in.link end2
      let last.in.link end1
      if([xcor] of end1 = [xcor] of end2) [
        if ([ycor] of end1 < [ycor] of end2)[
          ask product mouse-aux [
            set xcor tempx-end1
            if(aux-y < tempy-end1)[set ycor tempy-end1]
            if(aux-y > tempy-end2)[set ycor tempy-end2]
            if(aux-y >= tempy-end1 and aux-y <= tempy-end2)[set ycor aux-y]
            set Product.State "Movement"
            set heading link-heading-direction
            set last.node last.in.link
            set next.node next.in.link
          ]
        ]
        if ([ycor] of end1 > [ycor] of end2)[
          ask product mouse-aux [
            set xcor tempx-end1
            if(aux-y < tempy-end2)[set ycor tempy-end2]
            if(aux-y > tempy-end1)[set ycor tempy-end1]
            if(aux-y >= tempy-end2  and aux-y <= tempy-end1)[set ycor aux-y]
            set Product.State "Movement"
            set heading link-heading-direction
            set last.node last.in.link
            set next.node next.in.link
          ]
        ]
      ]
      if([ycor] of end1 = [ycor] of end2) [

        ask product mouse-aux [
            set ycor tempy-end1
            if(aux-x < tempx-end1)[set xcor tempx-end1]
            if(aux-x > tempx-end2)[set xcor tempx-end2]
            if(aux-x >= tempx-end1 and aux-x <= tempx-end2)[set xcor aux-x]
            set Product.State "Movement"
            set heading link-heading-direction
            set last.node last.in.link
            set next.node next.in.link
          ]
        ]
        if ([xcor] of end1 > [xcor] of end2)[
          ask product mouse-aux [
            set ycor tempy-end1
            if(aux-x < tempx-end2)[set xcor tempx-end2]
            if(aux-x > tempx-end1)[set xcor tempx-end1]
            if(aux-x >= tempx-end2 and aux-x <= tempx-end1)[set xcor aux-x]
            set Product.State "Movement"
            set heading link-heading-direction
            set last.node last.in.link
            set next.node next.in.link
          ]
        ]
      ]
    set mouse-aux 0
    ]




end

to Set.Sensors

  ;-- Simple Sensors (Entry to Machine)-----------------------

  set W9-Indicator 0

  create-sensors 1 [setxy 154 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S138
  create-sensors 1 [setxy 162 83 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S5"]       ; S139
  create-sensors 1 [setxy 175.5 103 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S6"]    ; S140
  create-sensors 1 [setxy 185 106 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S7"]      ; S141
  create-sensors 1 [setxy 185 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S8"]       ; S142

  set W1-Indicator 0

  create-sensors 1 [setxy 71 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]        ; S143
  create-sensors 1 [setxy 63 62 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S5"]        ; S144
  create-sensors 1 [setxy 49.5 42 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S6"]      ; S145
  create-sensors 1 [setxy 40 39  set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S7"]       ; S146
  create-sensors 1 [setxy 40 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S8"]        ; S147

  set W6-Indicator 0

  create-sensors 1 [setxy 75 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]        ; S148
  create-sensors 1 [setxy 83 83 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S5"]        ; S149
  create-sensors 1 [setxy 97.5 103 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S6"]     ; S150
  create-sensors 1 [setxy 107 106  set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S7"]     ; S151
  create-sensors 1 [setxy 107 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S8"]       ; S152

  set W16-Indicator 0

  create-sensors 1 [setxy 149 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]        ; S153
  create-sensors 1 [setxy 141 62 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S5"]        ; S154
  create-sensors 1 [setxy 127.5 42 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S6"]      ; S155
  create-sensors 1 [setxy 118 39  set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S7"]       ; S156
  create-sensors 1 [setxy 118 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S8"]        ; S157

  ;-- Machine Sensors ------------------------------------------

  set W7-Indicator 0
  create-sensors 1 [setxy 115 106 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S158

  set W10-Indicator 0
  create-sensors 1 [setxy 193 106 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S159

  set W12-Indicator 0
  create-sensors 1 [setxy 226 66.4 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]     ; S160

  set W14-Indicator 0
  create-sensors 1 [setxy 188 39 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S161

  set W17-Indicator 0
  create-sensors 1 [setxy 110 39 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S162

  set W2-Indicator 0
  create-sensors 1 [setxy 28.5 39 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S163

  set W4-Indicator 0
  create-sensors 1 [setxy 28.5 106 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]      ; S164


  ;-- Exit Sensors (Simple exit from machine) ------------------------------------------

  set W5-Indicator 0
  create-sensors 1 [setxy 41 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]          ; S165
  create-sensors 1 [setxy 63 81 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]          ; S166

  set W8-Indicator 0
  create-sensors 1 [setxy 119.8 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S167
  create-sensors 1 [setxy 141 81 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S168

  set W11-Indicator 0
  create-sensors 1 [setxy 194 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S169
  create-sensors 1 [setxy 217 79 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S170

  set W15-Indicator 0
  create-sensors 1 [setxy 184 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S171
  create-sensors 1 [setxy 162 64 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S172

  set W18-Indicator 0
  create-sensors 1 [setxy 106 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S173
  create-sensors 1 [setxy 83 64 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]          ; S174


  ;--- Exit and Entry Sensors W13 (These control the exist from machine and trigger entry to new machine if needed) ------------------------------------------

  set W13-Indicator 0

  create-sensors 1 [setxy 206 72.8 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S175

  create-sensors 1 [setxy 234 66.4 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S176                                                                   ; S176

  create-sensors 1 [setxy 196 39 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S177

  create-sensors 1 [setxy 193.4 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]       ; S178                                                                   ; S178

  create-sensors 1 [setxy 205.4 42 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S6"]       ; S179

  ;-- Double separate-control Sensors (Long conveyor and requires double checking for triggering) -------------------------------------------------

  set W3A-Indicator 0
  create-sensors 1 [setxy 18.6 52 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S180
  create-sensors 1 [setxy 7 64 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]            ; S181

  set W3B-Indicator 0

  create-sensors 1 [setxy 7 83 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]            ; S182
  create-sensors 1 [setxy 7.5 103 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S183
  create-sensors 1 [setxy 20 106 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]          ; S184
  create-sensors 1 [setxy 19.6 93 set shape "square" set color green set size 1.5 set signal 0 set Sensor.ID "S4"]         ; S185

end

to Set.Machines

  create-machines 1 [setxy 115 117 set size 16 set color 14.5 set heading 180 set shape "3.0-machine" set machine.name "M1"]  ; M186
  create-machines 1 [setxy 193 117 set size 16 set color 14.5 set heading 180 set shape "3.0-machine" set machine.name "M2"]  ; M187
  create-machines 1 [setxy 226 55.4 set size 16 set color 14.5 set heading 0 set shape "3.0-machine" set machine.name "M3"]   ; M188
  create-machines 1 [setxy 188 28 set size 16 set color 14.5 set heading 0 set shape "3.0-machine" set machine.name "M4"]     ; M189
  create-machines 1 [setxy 110 28 set size 16 set color 14.5 set heading 0 set shape "3.0-machine" set machine.name "M5"]     ; M190
  create-machines 1 [setxy 28.5 28 set size 16 set color 14.5 set heading 0 set shape "3.0-machine" set machine.name "M6"]    ; M191
  create-machines 1 [setxy 28.5 117 set size 16 set color 14.5 set heading 180 set shape "3.0-machine" set machine.name "M7"] ; M192


  ask machines with [machine.name = "M1"][      ; M186
    set Next.Completion  100000000
    set Machine.Operations.Type ["O8" "O9"]
    set Machine.Operations.Time [100 100]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M2"][     ; M187
    set Next.Completion  100000000
    set Machine.Operations.Type ["O1" "O2" "O4"]
    set Machine.Operations.Time [200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []

    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M3"][     ; M188
    set Next.Completion  100000000
    set Machine.Operations.Type ["O1" "O2" "O5"]
    set Machine.Operations.Time [200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M4"][     ; M189
    set Next.Completion  100000000
    set Machine.Operations.Type ["O3" "O4" "O5"]
    set Machine.Operations.Time [200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M5"][     ; M190
    set Next.Completion  100000000
    set Machine.Operations.Type ["O1" "O3" "O5" "O6"]
    set Machine.Operations.Time [200 200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M6"][     ; M191
    set Next.Completion  100000000
    set Machine.Operations.Type ["O2" "O3" "O4" "O6"]
    set Machine.Operations.Time [200 200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

  ask machines with [machine.name = "M7"][     ; M192
    set Next.Completion  100000000
    set Machine.Operations.Type ["O1" "O2" "O3" "O4" "O5"]
    set Machine.Operations.Time [200 200 200 200 200]
    set Machine.Atractiveness 1000000
    set Products.Queue []
    set machine.state "Idle"
    set Number.Products.Radio 0
    set label machine.name
    set label-color 0
  ]

end

to Set.operations

  set operations[]
  set operations lput ["M2" "M3" "M5" "M7"] operations       ; Operation 1
  set operations lput ["M2" "M3" "M6" "M7"] operations       ; Operation 2
  set operations lput ["M4" "M5" "M6" "M7"] operations       ; Operation 3
  set operations lput ["M2" "M4" "M6" "M7"] operations       ; Operation 4
  set operations lput ["M3" "M4" "M5" "M7"] operations       ; Operation 5
  set operations lput ["M5"] operations                      ; Operation 6
  set operations lput ["M6"] operations                      ; Operation 7
  set operations lput ["M1"] operations                      ; Operation 8
  set operations lput ["M1"] operations                      ; Operation 9

  set OperationDuration [200 200 200 200 200 200 200 100 100]

end

to Set.distances.Machines

  set distances[]
  set distances lput [1	111.3	201.8	186.6	125.5	212.1	298.4] distances ; M1 to rest
  set distances lput [287.9	1	124.6	109.4	187.2	273.7	360.8] distances ; M2 to rest
  set distances lput [247.4	161.8	1	69.13	146.9	233.4	320.2] distances ; M3 to rest
  set distances lput [212.3	126.8	217.3	1	111.9	198.4	285.2] distances ; M4 to rest
  set distances lput [129.6	211.7	302.2	187.6	1	115.6	202.2] distances ; M5 to rest
  set distances lput [208.1	290.1	380.7	365.5	304.4	1	121.2] distances ; M6 to rest
  set distances lput [120.9	203.1	293.5	278.4	217.3	139.5	1] distances ; M7 to rest


end

to Change.Gates.positions [#1 #2 #3 #4]     ; 1 and 2 are the passing gate 3 and 4 will be take it off

ask conveyor #3 #4 [let temp end2 ask end1 [face temp set addressed.to.node temp] set color 29 ask arrow Associated-Arrow [set hidden? True]]
ask conveyor #1 #2 [let temp end2 ask end1 [face temp set addressed.to.node temp] set color 5 ask arrow Associated-Arrow [set hidden? false]]

end

to Conveyor.Creation

  create.link.with.attributes 0 1 0.6 "default" "false"
  create.link.with.attributes 1 2 0.6 "curve1" "false"
  create.link.with.attributes 2 3 0.6 "default" "false"
  create.link.with.attributes 3 4 0.6 "curve2" "false"
  create.link.with.attributes 4 5 0.6 "default" "false"
  create.link.with.attributes 5 6 0.6 "curve2" "true"
  create.link.with.attributes 6 7 0.6 "default" "false"
  create.link.with.attributes 7 8 0.6 "curve2" "true"
  create.link.with.attributes 8 9 0.6 "default" "false"
  create.link.with.attributes 9 10 0.6 "curve2" "false"
  create.link.with.attributes 9 16 0.6 "curve3" "true"
  create.link.with.attributes 10 11 0.6 "default" "false"
  create.link.with.attributes 11 12 0.6 "curve1" "false"
  create.link.with.attributes 12 13 0.6 "default" "false"
  create.link.with.attributes 13 14 0.6 "curve1" "false"
  create.link.with.attributes 14 15 0.6 "default" "false"
  create.link.with.attributes 15 18 0.6 "curve2" "false"
  create.link.with.attributes 16 17 0.6 "default" "false"
  create.link.with.attributes 17 18 0.6 "curve3" "true"
  create.link.with.attributes 18 19 0.6 "default" "false"
  create.link.with.attributes 19 20 0.6 "curve2" "false"
  create.link.with.attributes 20 21 0.6 "default" "false"
  create.link.with.attributes 21 22 0.6 "curve1" "false"
  create.link.with.attributes 22 23 0.6 "curve1" "false"
  create.link.with.attributes 23 24 0.6 "default" "false"
  create.link.with.attributes 19 25 0.6 "curve3" "true"
  create.link.with.attributes 25 26 0.6 "default" "false"
  create.link.with.attributes 24 27 0.6 "curve2" "false"
  create.link.with.attributes 26 27 0.6 "curve3" "true"
  create.link.with.attributes 27 28 0.6 "default" "false"
  create.link.with.attributes 28 29 0.6 "curve2" "false"
  create.link.with.attributes 29 30 0.6 "default" "false"
  create.link.with.attributes 30 31 0.6 "curve1" "false"
  create.link.with.attributes 31 32 0.6 "default" "false"
  create.link.with.attributes 32 33 0.6 "curve1" "false"
  create.link.with.attributes 33 34 0.6 "default" "false"
  create.link.with.attributes 28 35 0.6 "curve3" "true"
  create.link.with.attributes 31 32 0.6 "default" "false"
  create.link.with.attributes 35 36 0.6 "default" "false"
  create.link.with.attributes 34 37 0.6 "curve2" "false"
  create.link.with.attributes 36 37 0.6 "curve3" "true"
  create.link.with.attributes 37 38 0.6 "default" "false"
  create.link.with.attributes 38 39 0.6 "curve3" "false"
  create.link.with.attributes 39 40 0.6 "default" "false"
  create.link.with.attributes 40 8 0.6 "curve3" "false"
  create.link.with.attributes 38 41 0.6 "curve2" "true"
  create.link.with.attributes 41 42 0.6 "default" "false"
  create.link.with.attributes 42 45 0.6 "curve2" "true"
  create.link.with.attributes 44 43 0.6 "default" "false"
  create.link.with.attributes 5 44 0.6 "curve3" "false"
  create.link.with.attributes 43 45 0.6 "curve3" "false"
  create.link.with.attributes 45 46 0.6 "default" "false"
  create.link.with.attributes 46 47 0.6 "curve2" "false"
  create.link.with.attributes 47 48 0.6 "default" "false"
  create.link.with.attributes 48 49 0.6 "curve1" "false"
  create.link.with.attributes 49 50 0.6 "default" "false"
  create.link.with.attributes 50 51 0.6 "curve1" "false"
  create.link.with.attributes 51 52 0.6 "default" "false"
  create.link.with.attributes 52 55 0.6 "curve2" "false"
  create.link.with.attributes 46 53 0.6 "curve3" "true"
  create.link.with.attributes 53 54 0.6 "default" "false"
  create.link.with.attributes 54 55 0.6 "curve3" "true"
  create.link.with.attributes 55 56 0.6 "default" "false"
  create.link.with.attributes 56 57 0.6 "curve3" "false"
  create.link.with.attributes 57 58 0.6 "default" "false"
  create.link.with.attributes 56 59 0.6 "curve2" "true"
  create.link.with.attributes 59 60 0.6 "default" "false"
  create.link.with.attributes 60 63 0.6 "curve2" "true"
  create.link.with.attributes 62 61 0.6 "default" "false"
  create.link.with.attributes 61 63 0.6 "curve3" "false"
  create.link.with.attributes 63 64 0.6 "default" "false"
  create.link.with.attributes 64 65 0.6 "curve2" "false"
  create.link.with.attributes 65 66 0.6 "default" "false"
  create.link.with.attributes 66 67 0.6 "curve1" "false"
  create.link.with.attributes 67 68 0.6 "default" "false"
  create.link.with.attributes 68 69 0.6 "curve1" "false"
  create.link.with.attributes 69 70 0.6 "default" "false"
  create.link.with.attributes 64 71 0.6 "curve3" "true"
  create.link.with.attributes 71 72 0.6 "default" "false"
  create.link.with.attributes 70 73 0.6 "curve2" "false"
  create.link.with.attributes 72 73 0.6 "curve3" "true"
  create.link.with.attributes 73 74 0.6 "default" "false"
  create.link.with.attributes 74 75 0.6 "curve2" "false"
  create.link.with.attributes 74 81 0.6 "curve3" "true"
  create.link.with.attributes 75 76 0.6 "default" "false"
  create.link.with.attributes 76 77 0.6 "curve1" "false"
  create.link.with.attributes 77 78 0.6 "default" "false"
  create.link.with.attributes 78 79 0.6 "curve1" "false"
  create.link.with.attributes 79 80 0.6 "default" "false"
  create.link.with.attributes 81 82 0.6 "default" "false"
  create.link.with.attributes 80 83 0.6 "curve2" "false"
  create.link.with.attributes 82 83 0.6 "curve3" "true"
  create.link.with.attributes 83 84 0.6 "default" "false"
  create.link.with.attributes 84 62 0.6 "curve3" "false"
  create.link.with.attributes 84 85 0.6 "curve2" "true"
  create.link.with.attributes 85 86 0.6 "default" "false"
  create.link.with.attributes 86 87 0.6 "curve2" "true"
  create.link.with.attributes 58 87 0.6 "curve3" "false"
  create.link.with.attributes 87 88 0.6 "default" "false"
  create.link.with.attributes 88 89 0.6 "curve3" "true"
  create.link.with.attributes 88 91 0.6 "curve2" "false"
  create.link.with.attributes 89 90 0.6 "default" "false"
  create.link.with.attributes 91 92 0.6 "default" "false"
  create.link.with.attributes 92 93 0.6 "curve1" "false"
  create.link.with.attributes 93 0 0.6 "default" "false"
  create.link.with.attributes 90 4 0.6 "curve3" "true"

  ask links [                                       ; cambiar despues para tenerlo en su definicion
    if (shape = "curve1") [set thickness 0.5]
    if (shape = "curve2") [set thickness 0.5]
    if (shape = "curve3") [set thickness 0.5]
  ]


end

to Direction.Arrows.Creation

  create.directions.conveyors 131.7 96.8 141.3
  create.directions.conveyors 128.3 90.5 90
  create.directions.conveyors 141 95.4 90
  create.directions.conveyors 137.2 88.4 147.0
  create.directions.conveyors 162 95.3 90
  create.directions.conveyors 165.7 88.9 29.5
  create.directions.conveyors 171.6 96.6 34.2
  create.directions.conveyors 175 90.7 90
  create.directions.conveyors 208.3 93 180
  create.directions.conveyors 201.9 89.3 119.5
  create.directions.conveyors 209.6 82.4 124.2
  create.directions.conveyors 203.7 79 180
  create.directions.conveyors 209.6 63.1 235.7
  create.directions.conveyors 203.7 66.5 180
  create.directions.conveyors 208.3 52 180
  create.directions.conveyors 201.9 55.7 240.4
  create.directions.conveyors 175 54.3 270
  create.directions.conveyors 171.7 48.4 325.8
  create.directions.conveyors 166 56.3 326.3
  create.directions.conveyors 162 49.3 270
  create.directions.conveyors 141 49.6 270
  create.directions.conveyors 137.2 56.2 210.9
  create.directions.conveyors 131.7 48.2 218.6
  create.directions.conveyors 128.3 54.5 270
  create.directions.conveyors 97 54.3 270
  create.directions.conveyors 93.7 48.4 325.8
  create.directions.conveyors 86.7 56.1 330.4
  create.directions.conveyors 83 49.7 270
  create.directions.conveyors 63 49.7 270
  create.directions.conveyors 59.3 56.1 209.5
  create.directions.conveyors 50 54.3 270
  create.directions.conveyors 53.4 48.4 214.2
  create.directions.conveyors 11.1 55.7 299.5
  create.directions.conveyors 4.7 52 0
  create.directions.conveyors 4.7 93 0
  create.directions.conveyors 11.1 89.3 60.4
  create.directions.conveyors 50 90.7 90
  create.directions.conveyors 53.3 96.6 145.7
  create.directions.conveyors 63 95.3 90
  create.directions.conveyors 59.3 88.9 150.4
  create.directions.conveyors 83 95.3 90
  create.directions.conveyors 86.7 88.9 29.5
  create.directions.conveyors 93.6 96.6 34.2
  create.directions.conveyors 97 90.7 90

end

to create.link.with.attributes [#1 #2 #3 #4 #5]   ; Creation Phase. For creating automatically the link with the attributes
  ask turtle #1 [create-conveyor-to turtle #2 face turtle #2 ]
  ask conveyor #1 #2 [set color gray set thickness #3 set shape #4 set Associated-Arrow "None" set Default.position #5]
end

to create.directions.conveyors [#1 #2 #3]

  create-arrows 1 [
    setxy  #1 #2
    set heading #3
    set shape "arrow-direction"
    set color 97
    set size 4
  ]

end

to Set.Associated.Arrow

  ask conveyors with [shape = "default"] [set Associated-Arrow "Not Associated"]
  ask conveyors with [shape = "curve"] [set Associated-Arrow "Not Associated"]
  ask conveyors with [shape = "curve2" or shape = "curve3"][
    let temp end2
    ask end1 [face temp ask arrows in-cone 5 90 [set temp who]]
    set Associated-Arrow temp
  ]

end

to Set.Default.Layout

  ;ask conveyors [ifelse (Default.position = "true")[set Default.position "false"][set Default.position "true"]]


  ask conveyors with [Default.position = "true"][let temp end2 ask end1 [face temp]]
  ask conveyors with [Default.position = "false" and shape = "curve2"][set color 29 ask arrow Associated-Arrow [set hidden? true]]
  ask conveyors with [Default.position = "false" and shape = "curve3"][set color 29 ask arrow Associated-Arrow [set hidden? true]]

  ask conveyors with [color = gray][
    let temp end2
    ask end1 [set Addressed.To.Node temp]
  ]


end


to Set.aditional.nodes

  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N193
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N194
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N195
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N196
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N197
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N198
  create-nodes 1 [setxy 0 0 set size 0.1 set shape "circle" set color black set hidden? true set Addressed.To.Node ""]            ; N199

end

to Node.Creation

  create-nodes 1 [setxy 115 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N0
  create-nodes 1 [setxy 123 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N1
  create-nodes 1 [setxy 128 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N2
  create-nodes 1 [setxy 128 98 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N3
  create-nodes 1 [setxy 132 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N4
  create-nodes 1 [setxy 137.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N5
  create-nodes 1 [setxy 144.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N6
  create-nodes 1 [setxy 158.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N7
  create-nodes 1 [setxy 165.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N8
  create-nodes 1 [setxy 171.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N9
  create-nodes 1 [setxy 175 98 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N10
  create-nodes 1 [setxy 175 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N11
  create-nodes 1 [setxy 180 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N12
  create-nodes 1 [setxy 201 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N13
  create-nodes 1 [setxy 206 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N14
  create-nodes 1 [setxy 206 96.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N15
  create-nodes 1 [setxy 178.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N16
  create-nodes 1 [setxy 200 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N17
  create-nodes 1 [setxy 206 89.6 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N18
  create-nodes 1 [setxy 206 82.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N19
  create-nodes 1 [setxy 211 79 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N20
  create-nodes 1 [setxy 241 79 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N21
  create-nodes 1 [setxy 246 72.7 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N22
  create-nodes 1 [setxy 241 66.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N23
  create-nodes 1 [setxy 211 66.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N24
  create-nodes 1 [setxy 206 75.6 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N25
  create-nodes 1 [setxy 206 69.9 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N26
  create-nodes 1 [setxy 206 63 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N27
  create-nodes 1 [setxy 206 55.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N28
  create-nodes 1 [setxy 206 48.6 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N29
  create-nodes 1 [setxy 206 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N30
  create-nodes 1 [setxy 201 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N31
  create-nodes 1 [setxy 180 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N32
  create-nodes 1 [setxy 175 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N33
  create-nodes 1 [setxy 175 47 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N34
  create-nodes 1 [setxy 200 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N35
  create-nodes 1 [setxy 178.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N36
  create-nodes 1 [setxy 171.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N37
  create-nodes 1 [setxy 166 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N38
  create-nodes 1 [setxy 162 58 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N39
  create-nodes 1 [setxy 162 87 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N40
  create-nodes 1 [setxy 159.2 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N41
  create-nodes 1 [setxy 144.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N42
  create-nodes 1 [setxy 141 58 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N43
  create-nodes 1 [setxy 141 87 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N44
  create-nodes 1 [setxy 137.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N45
  create-nodes 1 [setxy 132 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N46
  create-nodes 1 [setxy 128 47 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N47
  create-nodes 1 [setxy 128 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N48
  create-nodes 1 [setxy 123 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N49
  create-nodes 1 [setxy 102 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N50
  create-nodes 1 [setxy 97 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N51
  create-nodes 1 [setxy 97 47 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N52
  create-nodes 1 [setxy 124.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N53
  create-nodes 1 [setxy 100.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N54
  create-nodes 1 [setxy 93.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N55
  create-nodes 1 [setxy 86.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N56
  create-nodes 1 [setxy 83 58 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N57
  create-nodes 1 [setxy 83 87 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N58
  create-nodes 1 [setxy 79.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N59
  create-nodes 1 [setxy 66.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N60
  create-nodes 1 [setxy 63 58 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N61
  create-nodes 1 [setxy 63 87 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N62
  create-nodes 1 [setxy 59.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N63
  create-nodes 1 [setxy 53.4 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N64
  create-nodes 1 [setxy 50 47 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N65
  create-nodes 1 [setxy 50 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N66
  create-nodes 1 [setxy 45 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N67
  create-nodes 1 [setxy 12 39 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N68
  create-nodes 1 [setxy 7 45 set size 1 set shape "circle" set color black set Addressed.To.Node ""]      ; N69
  create-nodes 1 [setxy 7 48.6 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N70
  create-nodes 1 [setxy 46.6 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N71
  create-nodes 1 [setxy 13 52 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N72
  create-nodes 1 [setxy 7 55.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N73
  create-nodes 1 [setxy 7 89.6 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N74
  create-nodes 1 [setxy 7 96.4 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N75
  create-nodes 1 [setxy 7 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N76
  create-nodes 1 [setxy 12 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N77
  create-nodes 1 [setxy 45 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N78
  create-nodes 1 [setxy 50 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N79
  create-nodes 1 [setxy 50 98 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N80
  create-nodes 1 [setxy 13 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N81
  create-nodes 1 [setxy 46.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N82
  create-nodes 1 [setxy 53.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N83
  create-nodes 1 [setxy 59.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N84
  create-nodes 1 [setxy 66.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N85
  create-nodes 1 [setxy 79.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N86
  create-nodes 1 [setxy 86.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N87
  create-nodes 1 [setxy 93.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N88
  create-nodes 1 [setxy 100.4 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N89
  create-nodes 1 [setxy 124.6 93 set size 1 set shape "circle" set color black set Addressed.To.Node ""]  ; N90
  create-nodes 1 [setxy 97 98 set size 1 set shape "circle" set color black set Addressed.To.Node ""]     ; N91
  create-nodes 1 [setxy 97 100 set size 1 set shape "circle" set color black set Addressed.To.Node ""]    ; N92
  create-nodes 1 [setxy 102 106 set size 1 set shape "circle" set color black set Addressed.To.Node ""]   ; N93

end
@#$#@#$#@
GRAPHICS-WINDOW
295
11
1558
675
-1
-1
5.0
1
13
1
1
1
0
1
1
1
0
250
0
130
0
0
1
ticks
60.0

BUTTON
10
63
96
96
Setup
Setup
NIL
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

BUTTON
99
63
185
96
Step
Go
NIL
1
T
OBSERVER
NIL
N
NIL
NIL
1

BUTTON
188
63
274
96
Play
Go
T
1
T
OBSERVER
NIL
NIL
NIL
NIL
1

MONITOR
10
11
135
56
NIL
Simulated.Time
0
1
11

SWITCH
139
11
272
44
Product-Label?
Product-Label?
1
1
-1000

MONITOR
11
106
275
151
Available for launch
precision Time-for-Possible-launching 0
17
1
11

CHOOSER
11
241
276
286
Reactivity.rule
Reactivity.rule
"Rule 1 - Random Machine" "Rule 2 - Nearest Machine" "Rule 3 - Potential Fields"
0

MONITOR
10
192
275
237
Count
count products with [product.state != \"death\"]
17
1
11

CHOOSER
13
370
151
415
Modeling.Type
Modeling.Type
"Deterministic" "Stochastic"
0

TEXTBOX
14
293
398
358
Reactivity rule: \nChosses next machine after an operation is completed\nRule 1 - Random posible machine\nRule 2 - Nearest posible machine \nRule 3 - Potential Fields (Attractivness and distance)
10
0.0
1

CHOOSER
14
438
153
483
Interval.logs
Interval.logs
100 300 500
0

TEXTBOX
19
497
169
539
100 interval en simulated time son 10 segundos reales
11
0.0
1

@#$#@#$#@
## WHAT IS IT?

(a general understanding of what the model is trying to show or explain)

## HOW IT WORKS

(what rules the agents use to create the overall behavior of the model)

## HOW TO USE IT

(how to use the model, including a description of each of the items in the Interface tab)

## THINGS TO NOTICE

(suggested things for the user to notice while running the model)

## THINGS TO TRY

(suggested things for the user to try to do (move sliders, switches, etc.) with the model)

## EXTENDING THE MODEL

(suggested things to add or change in the Code tab to make the model more complicated, detailed, accurate, etc.)

## NETLOGO FEATURES

(interesting or unusual features of NetLogo that the model uses, particularly in the Code tab; or where workarounds were needed for missing features)

## RELATED MODELS

(models in the NetLogo Models Library and elsewhere which are of related interest)

## CREDITS AND REFERENCES

(a reference to the model's URL on the web if it has one, as well as any other necessary credits, citations, and links)
@#$#@#$#@
default
true
0
Polygon -7500403 true true 150 5 40 250 150 205 260 250

0-plate
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 128 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75

1.0-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

1.1-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 143 14
Circle -1 true false 158 113 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

1.2-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 128 113 14
Circle -1 true false 128 143 14
Circle -13345367 true false 158 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 158 113 14

1.3-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 143 14
Circle -13345367 true false 128 113 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 143 14
Circle -1 true false 158 113 14

1.4-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -955883 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 143 165 157
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14

1.5-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -2674135 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -2674135 true false 158 113 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 143 166 157
Rectangle -955883 true false 128 118 141 150
Rectangle -2674135 true false 106 112 166 127
Rectangle -2674135 true false 158 119 171 151
Circle -2674135 true false 158 143 14

1.6-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -2674135 true false 98 113 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -2674135 true false 158 113 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 118 141 150
Rectangle -2674135 true false 106 112 166 127
Rectangle -2674135 true false 158 119 171 151
Circle -6459832 true false 158 143 14
Rectangle -6459832 true false 106 143 136 157
Rectangle -6459832 true false 136 143 166 157

1.f-product-a
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -2674135 true false 98 113 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -2674135 true false 158 113 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 118 141 150
Rectangle -2674135 true false 106 112 166 127
Rectangle -2674135 true false 158 119 171 151
Circle -6459832 true false 158 143 14
Rectangle -6459832 true false 106 143 136 157
Rectangle -6459832 true false 136 143 166 157
Circle -16777216 true false 128 143 13

2.0-product-i
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

2.1-product-i
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -13345367 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

2.2-product-i
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -13345367 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

2.3-product-i
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -6459832 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 136 143 165 157
Circle -1 true false 128 113 14
Rectangle -6459832 true false 106 143 135 157

2.f-product-i
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -6459832 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 136 143 165 157
Circle -1 true false 128 113 14
Rectangle -6459832 true false 106 143 135 157
Circle -16777216 true false 128 143 14

3.0-machine
true
0
Rectangle -7500403 true true 105 15 195 165

3.0-product-p
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

3.1-product-p
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

3.2-product-p
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -13345367 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

3.3-product-p
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -955883 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 143 165 157
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14

3.f-product-p
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -2674135 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -2674135 true false 158 113 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 143 165 157
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14
Rectangle -2674135 true false 106 113 135 127
Rectangle -2674135 true false 136 113 165 127
Rectangle -2674135 true false 158 121 171 145
Circle -2674135 true false 158 143 14

4.0-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

4.1-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

4.2-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -13345367 true false 128 113 14

4.3-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -13345367 true false 128 113 14

4.4-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 143 14
Circle -955883 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 106 113 135 127
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14

4.5-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -955883 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14
Rectangle -955883 true false 106 143 135 157
Rectangle -955883 true false 98 121 111 145
Rectangle -955883 true false 106 113 135 127
Circle -955883 true false 98 113 14

4.6-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -955883 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 121 141 145
Circle -6459832 true false 128 113 14
Rectangle -955883 true false 106 143 135 157
Rectangle -955883 true false 98 121 111 145
Rectangle -6459832 true false 106 113 135 127
Circle -6459832 true false 98 113 14
Rectangle -6459832 true false 136 113 165 127

4.f-product-b
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -955883 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 121 141 145
Circle -6459832 true false 128 113 14
Rectangle -955883 true false 106 143 135 157
Rectangle -955883 true false 98 121 111 145
Rectangle -6459832 true false 106 113 135 127
Circle -16777216 true false 98 113 14
Rectangle -6459832 true false 136 113 165 127

5.0-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

5.1-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

5.2-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -13345367 true false 128 113 14

5.3-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -13345367 true false 128 113 14

5.4-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -955883 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 113 165 127
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14

5.5-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -955883 true false 98 143 14
Circle -955883 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -955883 true false 158 113 14
Circle -1 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 136 113 165 127
Rectangle -955883 true false 128 121 141 145
Circle -955883 true false 128 113 14
Rectangle -955883 true false 98 121 111 145
Rectangle -955883 true false 106 113 135 127

5.f-product-e
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -955883 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -2674135 true false 158 113 14
Circle -2674135 true false 158 143 14
Circle -955883 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -955883 true false 128 121 141 145
Circle -2674135 true false 128 113 14
Rectangle -955883 true false 98 121 111 145
Rectangle -2674135 true false 106 113 135 127
Rectangle -2674135 true false 158 121 171 145
Rectangle -2674135 true false 136 113 165 127
Circle -2674135 true false 98 113 14

6.0-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

6.1-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

6.2-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

6.3-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -13345367 true false 98 113 14
Circle -1 true false 98 143 14
Circle -13345367 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -13345367 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

6.4-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -6459832 true false 98 113 14
Circle -13345367 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 136 113 165 127
Circle -6459832 true false 128 113 14
Rectangle -6459832 true false 106 113 135 127

6.5-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -6459832 true false 98 113 14
Circle -6459832 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 97 118 111 151
Circle -6459832 true false 128 113 14
Rectangle -6459832 true false 106 113 135 127
Rectangle -6459832 true false 136 113 165 127
Rectangle -6459832 true false 97 150 111 183

6.6-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -6459832 true false 98 113 14
Circle -6459832 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 97 118 111 151
Circle -6459832 true false 128 113 14
Rectangle -6459832 true false 106 113 135 127
Rectangle -6459832 true false 136 113 165 127
Rectangle -6459832 true false 97 150 111 183
Circle -16777216 true false 128 113 14

6.f-product-l
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 143 14
Circle -6459832 true false 98 113 14
Circle -6459832 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 97 118 111 151
Circle -6459832 true false 128 113 14
Rectangle -6459832 true false 106 113 135 127
Rectangle -6459832 true false 136 113 165 127
Rectangle -6459832 true false 97 150 111 183
Circle -16777216 true false 128 113 14
Circle -16777216 true false 98 143 14

7.0-product-t
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -1 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

7.1-product-t
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -13345367 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

7.2-product-t
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -1 true false 98 113 14
Circle -1 true false 98 143 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -13345367 true false 158 143 14
Circle -13345367 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Circle -1 true false 128 113 14

7.3-product-t
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -1 true false 158 113 14
Circle -6459832 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -1 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 136 143 165 157
Circle -1 true false 128 113 14
Rectangle -6459832 true false 106 143 135 157

7.f-product-t
true
0
Rectangle -7500403 true true 90 75 210 225
Circle -1 true false 128 83 14
Circle -1 true false 158 83 14
Circle -1 true false 188 83 14
Circle -1 true false 98 83 14
Circle -6459832 true false 98 143 14
Circle -1 true false 98 113 14
Circle -1 true false 98 173 14
Circle -1 true false 98 203 14
Circle -1 true false 128 203 14
Circle -1 true false 158 203 14
Circle -1 true false 188 203 14
Circle -1 true false 188 173 14
Circle -1 true false 188 143 14
Circle -1 true false 188 113 14
Circle -6459832 true false 158 113 14
Circle -6459832 true false 158 143 14
Circle -1 true false 128 143 14
Circle -1 true false 128 173 14
Circle -6459832 true false 158 173 14
Polygon -7500403 true true 135 75 165 75 150 60 135 75
Rectangle -6459832 true false 136 143 165 157
Circle -1 true false 128 113 14
Rectangle -6459832 true false 106 143 135 157
Rectangle -6459832 true false 158 119 171 152
Rectangle -6459832 true false 158 149 171 182

airplane
true
0
Polygon -7500403 true true 150 0 135 15 120 60 120 105 15 165 15 195 120 180 135 240 105 270 120 285 150 270 180 285 210 270 165 240 180 180 285 195 285 165 180 105 180 60 165 15

arrow-direction
true
0
Polygon -7500403 true true 150 0 90 75 135 75 135 285 165 285 165 75 210 75

box
false
0
Polygon -7500403 true true 150 285 285 225 285 75 150 135
Polygon -7500403 true true 150 135 15 75 150 15 285 75
Polygon -7500403 true true 15 75 15 225 150 285 150 135
Line -16777216 false 150 285 150 135
Line -16777216 false 150 135 15 75
Line -16777216 false 150 135 285 75

bug
true
0
Circle -7500403 true true 96 182 108
Circle -7500403 true true 110 127 80
Circle -7500403 true true 110 75 80
Line -7500403 true 150 100 80 30
Line -7500403 true 150 100 220 30

butterfly
true
0
Polygon -7500403 true true 150 165 209 199 225 225 225 255 195 270 165 255 150 240
Polygon -7500403 true true 150 165 89 198 75 225 75 255 105 270 135 255 150 240
Polygon -7500403 true true 139 148 100 105 55 90 25 90 10 105 10 135 25 180 40 195 85 194 139 163
Polygon -7500403 true true 162 150 200 105 245 90 275 90 290 105 290 135 275 180 260 195 215 195 162 165
Polygon -16777216 true false 150 255 135 225 120 150 135 120 150 105 165 120 180 150 165 225
Circle -16777216 true false 135 90 30
Line -16777216 false 150 105 195 60
Line -16777216 false 150 105 105 60

car
false
0
Polygon -7500403 true true 300 180 279 164 261 144 240 135 226 132 213 106 203 84 185 63 159 50 135 50 75 60 0 150 0 165 0 225 300 225 300 180
Circle -16777216 true false 180 180 90
Circle -16777216 true false 30 180 90
Polygon -16777216 true false 162 80 132 78 134 135 209 135 194 105 189 96 180 89
Circle -7500403 true true 47 195 58
Circle -7500403 true true 195 195 58

circle
false
0
Circle -7500403 true true 0 0 300

circle 2
false
0
Circle -7500403 true true 0 0 300
Circle -16777216 true false 30 30 240

cow
false
0
Polygon -7500403 true true 200 193 197 249 179 249 177 196 166 187 140 189 93 191 78 179 72 211 49 209 48 181 37 149 25 120 25 89 45 72 103 84 179 75 198 76 252 64 272 81 293 103 285 121 255 121 242 118 224 167
Polygon -7500403 true true 73 210 86 251 62 249 48 208
Polygon -7500403 true true 25 114 16 195 9 204 23 213 25 200 39 123

cylinder
false
0
Circle -7500403 true true 0 0 300

dot
false
0
Circle -7500403 true true 90 90 120

face happy
false
0
Circle -7500403 true true 8 8 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Polygon -16777216 true false 150 255 90 239 62 213 47 191 67 179 90 203 109 218 150 225 192 218 210 203 227 181 251 194 236 217 212 240

face neutral
false
0
Circle -7500403 true true 8 7 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Rectangle -16777216 true false 60 195 240 225

face sad
false
0
Circle -7500403 true true 8 8 285
Circle -16777216 true false 60 75 60
Circle -16777216 true false 180 75 60
Polygon -16777216 true false 150 168 90 184 62 210 47 232 67 244 90 220 109 205 150 198 192 205 210 220 227 242 251 229 236 206 212 183

fish
false
0
Polygon -1 true false 44 131 21 87 15 86 0 120 15 150 0 180 13 214 20 212 45 166
Polygon -1 true false 135 195 119 235 95 218 76 210 46 204 60 165
Polygon -1 true false 75 45 83 77 71 103 86 114 166 78 135 60
Polygon -7500403 true true 30 136 151 77 226 81 280 119 292 146 292 160 287 170 270 195 195 210 151 212 30 166
Circle -16777216 true false 215 106 30

flag
false
0
Rectangle -7500403 true true 60 15 75 300
Polygon -7500403 true true 90 150 270 90 90 30
Line -7500403 true 75 135 90 135
Line -7500403 true 75 45 90 45

flower
false
0
Polygon -10899396 true false 135 120 165 165 180 210 180 240 150 300 165 300 195 240 195 195 165 135
Circle -7500403 true true 85 132 38
Circle -7500403 true true 130 147 38
Circle -7500403 true true 192 85 38
Circle -7500403 true true 85 40 38
Circle -7500403 true true 177 40 38
Circle -7500403 true true 177 132 38
Circle -7500403 true true 70 85 38
Circle -7500403 true true 130 25 38
Circle -7500403 true true 96 51 108
Circle -16777216 true false 113 68 74
Polygon -10899396 true false 189 233 219 188 249 173 279 188 234 218
Polygon -10899396 true false 180 255 150 210 105 210 75 240 135 240

house
false
0
Rectangle -7500403 true true 45 120 255 285
Rectangle -16777216 true false 120 210 180 285
Polygon -7500403 true true 15 120 150 15 285 120
Line -16777216 false 30 120 270 120

leaf
false
0
Polygon -7500403 true true 150 210 135 195 120 210 60 210 30 195 60 180 60 165 15 135 30 120 15 105 40 104 45 90 60 90 90 105 105 120 120 120 105 60 120 60 135 30 150 15 165 30 180 60 195 60 180 120 195 120 210 105 240 90 255 90 263 104 285 105 270 120 285 135 240 165 240 180 270 195 240 210 180 210 165 195
Polygon -7500403 true true 135 195 135 240 120 255 105 255 105 285 135 285 165 240 165 195

line
true
0
Line -7500403 true 150 0 150 300

line half
true
0
Line -7500403 true 150 0 150 150

pentagon
false
0
Polygon -7500403 true true 150 15 15 120 60 285 240 285 285 120

person
false
0
Circle -7500403 true true 110 5 80
Polygon -7500403 true true 105 90 120 195 90 285 105 300 135 300 150 225 165 300 195 300 210 285 180 195 195 90
Rectangle -7500403 true true 127 79 172 94
Polygon -7500403 true true 195 90 240 150 225 180 165 105
Polygon -7500403 true true 105 90 60 150 75 180 135 105

plant
false
0
Rectangle -7500403 true true 135 90 165 300
Polygon -7500403 true true 135 255 90 210 45 195 75 255 135 285
Polygon -7500403 true true 165 255 210 210 255 195 225 255 165 285
Polygon -7500403 true true 135 180 90 135 45 120 75 180 135 210
Polygon -7500403 true true 165 180 165 210 225 180 255 120 210 135
Polygon -7500403 true true 135 105 90 60 45 45 75 105 135 135
Polygon -7500403 true true 165 105 165 135 225 105 255 45 210 60
Polygon -7500403 true true 135 90 120 45 150 15 180 45 165 90

sheep
false
15
Circle -1 true true 203 65 88
Circle -1 true true 70 65 162
Circle -1 true true 150 105 120
Polygon -7500403 true false 218 120 240 165 255 165 278 120
Circle -7500403 true false 214 72 67
Rectangle -1 true true 164 223 179 298
Polygon -1 true true 45 285 30 285 30 240 15 195 45 210
Circle -1 true true 3 83 150
Rectangle -1 true true 65 221 80 296
Polygon -1 true true 195 285 210 285 210 240 240 210 195 210
Polygon -7500403 true false 276 85 285 105 302 99 294 83
Polygon -7500403 true false 219 85 210 105 193 99 201 83

square
false
0
Rectangle -7500403 true true 30 30 270 270

square 2
false
0
Rectangle -7500403 true true 30 30 270 270
Rectangle -16777216 true false 60 60 240 240

star
false
0
Polygon -7500403 true true 151 1 185 108 298 108 207 175 242 282 151 216 59 282 94 175 3 108 116 108

target
false
0
Circle -7500403 true true 0 0 300
Circle -16777216 true false 30 30 240
Circle -7500403 true true 60 60 180
Circle -16777216 true false 90 90 120
Circle -7500403 true true 120 120 60

tree
false
0
Circle -7500403 true true 118 3 94
Rectangle -6459832 true false 120 195 180 300
Circle -7500403 true true 65 21 108
Circle -7500403 true true 116 41 127
Circle -7500403 true true 45 90 120
Circle -7500403 true true 104 74 152

triangle
false
0
Polygon -7500403 true true 150 30 15 255 285 255

triangle 2
false
0
Polygon -7500403 true true 150 30 15 255 285 255
Polygon -16777216 true false 151 99 225 223 75 224

truck
false
0
Rectangle -7500403 true true 4 45 195 187
Polygon -7500403 true true 296 193 296 150 259 134 244 104 208 104 207 194
Rectangle -1 true false 195 60 195 105
Polygon -16777216 true false 238 112 252 141 219 141 218 112
Circle -16777216 true false 234 174 42
Rectangle -7500403 true true 181 185 214 194
Circle -16777216 true false 144 174 42
Circle -16777216 true false 24 174 42
Circle -7500403 false true 24 174 42
Circle -7500403 false true 144 174 42
Circle -7500403 false true 234 174 42

turtle
true
0
Polygon -10899396 true false 215 204 240 233 246 254 228 266 215 252 193 210
Polygon -10899396 true false 195 90 225 75 245 75 260 89 269 108 261 124 240 105 225 105 210 105
Polygon -10899396 true false 105 90 75 75 55 75 40 89 31 108 39 124 60 105 75 105 90 105
Polygon -10899396 true false 132 85 134 64 107 51 108 17 150 2 192 18 192 52 169 65 172 87
Polygon -10899396 true false 85 204 60 233 54 254 72 266 85 252 107 210
Polygon -7500403 true true 119 75 179 75 209 101 224 135 220 225 175 261 128 261 81 224 74 135 88 99

wheel
false
0
Circle -7500403 true true 3 3 294
Circle -16777216 true false 30 30 240
Line -7500403 true 150 285 150 15
Line -7500403 true 15 150 285 150
Circle -7500403 true true 120 120 60
Line -7500403 true 216 40 79 269
Line -7500403 true 40 84 269 221
Line -7500403 true 40 216 269 79
Line -7500403 true 84 40 221 269

wolf
false
0
Polygon -16777216 true false 253 133 245 131 245 133
Polygon -7500403 true true 2 194 13 197 30 191 38 193 38 205 20 226 20 257 27 265 38 266 40 260 31 253 31 230 60 206 68 198 75 209 66 228 65 243 82 261 84 268 100 267 103 261 77 239 79 231 100 207 98 196 119 201 143 202 160 195 166 210 172 213 173 238 167 251 160 248 154 265 169 264 178 247 186 240 198 260 200 271 217 271 219 262 207 258 195 230 192 198 210 184 227 164 242 144 259 145 284 151 277 141 293 140 299 134 297 127 273 119 270 105
Polygon -7500403 true true -1 195 14 180 36 166 40 153 53 140 82 131 134 133 159 126 188 115 227 108 236 102 238 98 268 86 269 92 281 87 269 103 269 113

x
false
0
Polygon -7500403 true true 270 75 225 30 30 225 75 270
Polygon -7500403 true true 30 75 75 30 270 225 225 270
@#$#@#$#@
NetLogo 6.4.0
@#$#@#$#@
@#$#@#$#@
@#$#@#$#@
<experiments>
  <experiment name="Test" repetitions="6" runMetricsEveryStep="false">
    <setup>setup</setup>
    <go>go</go>
    <enumeratedValueSet variable="Interval.logs">
      <value value="100"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Modeling.Type">
      <value value="&quot;Deterministic&quot;"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Product-Label?">
      <value value="false"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Reactivity.rule">
      <value value="&quot;Rule 1 - Random Machine&quot;"/>
    </enumeratedValueSet>
  </experiment>
  <experiment name="SofiaTest" repetitions="3" runMetricsEveryStep="false">
    <setup>setup</setup>
    <go>go</go>
    <enumeratedValueSet variable="Interval.logs">
      <value value="100"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Modeling.Type">
      <value value="&quot;Deterministic&quot;"/>
      <value value="&quot;Stochastic&quot;"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Product-Label?">
      <value value="false"/>
    </enumeratedValueSet>
    <enumeratedValueSet variable="Reactivity.rule">
      <value value="&quot;Rule 1 - Random Machine&quot;"/>
      <value value="&quot;Rule 3 - Potential Fields&quot;"/>
    </enumeratedValueSet>
  </experiment>
</experiments>
@#$#@#$#@
@#$#@#$#@
default
0.0
-0.2 0 0.0 1.0
0.0 1 1.0 0.0
0.2 0 0.0 1.0
link direction
true
0

curve1
4.0
-0.2 0 0.0 1.0
0.0 1 1.0 0.0
0.2 0 0.0 1.0
link direction
true
0

curve2
-2.0
-0.2 0 0.0 1.0
0.0 1 1.0 0.0
0.2 0 0.0 1.0
link direction
true
0

curve3
2.0
-0.2 0 0.0 1.0
0.0 1 1.0 0.0
0.2 0 0.0 1.0
link direction
true
0
@#$#@#$#@
0
@#$#@#$#@
