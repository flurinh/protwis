 function mergeSVG(div) {
     var SVG = $('#'+div).find('svg')[0];
     h = parseInt($(SVG).attr('height'));
     w = parseInt($(SVG).attr('width'));
     var legend = $('#legend').find('svg')[0];
     h2 = parseInt($(legend).attr('height'));
     w2 = parseInt($(legend).attr('width'));
     leg_w = (w-w2)/2
     SVG.setAttribute('height', (h + h2));
     if (w2 > w) {
         SVG.setAttribute('width', (w2));
         leg_w = 0
         svg_w = Math.abs(w-w2)/2
     } else {
         leg_w = Math.abs(w-w2)/2
         svg_w = 0
     };
     for (i = 0; i < legend.children.length; i++) {
         legend.children[i].setAttribute('transform', 'translate ('+leg_w.toString()+' ' + h.toString()+')');
         $(SVG).append(legend.children[i]);
     };
 };
 $(window).on("load", function () {
    //Unique crystallized receptors graph
    nv.addGraph(function () {
        var datum = data_unique_cryst_container;
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'))
            .showMaxMin(false);


        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#unique_cryst_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#unique_cryst_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //Unique crystals/year
    nv.addGraph(function () {
        var datum = data_unique_cryst_year_container;
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum));


        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#unique_cryst_year_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#unique_cryst_year_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //All crystals/year
    nv.addGraph(function () {
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'));

        var datum = data_cryst_year_container;

        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#cryst_year_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#cryst_year_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //Unique crystallized receptors per class graph
    nv.addGraph(function () {
        var datum = data_unique_class_cryst_container;
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'))
            .showMaxMin(false);


        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#unique_cryst_class_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#unique_cryst_class_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //Unique crystals/year per class
    nv.addGraph(function () {
        var datum = data_unique_class_cryst_year_container;
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum));


        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#unique_class_cryst_year_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#unique_class_cryst_year_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //All crystals/year per class
    nv.addGraph(function () {
        var chart = nv.models.multiBarChart()
            .reduceXTicks(false)
            .stacked(true)
            .margin({ top: 30, right: 60, bottom: 20, left: 60 })
            .color(d3.scale.category20().range());
        chart.yAxis
            .tickFormat(d3.format(',f'));

        var datum = data_cryst_class_year_container;

        var yAxis2 = nv.models.axis()
            .scale(chart.yScale())
            .showMaxMin(false)
            .tickFormat(d3.format(',f'))
            ._ticks(nv.utils.calcTicksY(400 / 36, datum))
            .tickPadding(0)
            .orient("right");

        d3.select('#cryst_class_year_container svg')
            .datum(datum)
            .transition().duration(500)
            .call(chart);
        d3.select('#cryst_class_year_container svg').selectAll('g.nv-wrap.nv-multiBarWithLegend').append("g")
            .attr("class", "nv-y nv-axis")
            .attr("transform", "translate(680, 0)")
            .call(yAxis2);
    });
    //Resolution coverage graph
    //nv.addGraph(function () {
    //    var chart = nv.models.discreteBarChart()
    //        .margin({ top: 30, right: 60, bottom: 20, left: 60 })
    //        .color(d3.scale.category20().range());
    //    chart.yAxis
    //        .tickFormat(d3.format(',f'));

    //    var datum = data_reso_container;

    //    var yAxis2 = nv.models.axis()
    //        .scale(chart.yScale())
    //        .showMaxMin(false)
    //        .tickFormat(d3.format(',f'))
    //        ._ticks( nv.utils.calcTicksY(400/36, datum) )
    //        .tickPadding(0)
    //        .orient("right");

    //    d3.select('#reso_container svg')
    //        .datum(datum)
    //        .transition().duration(500)
    //        .call(chart);
    //    d3.select('#reso_container svg').selectAll('g.nv-wrap.nv-discreteBarWithAxes').append("g")
    //        .attr("class", "nv-y nv-axis")
    //        .attr("transform", "translate(740, 30)")
    //        .call(yAxis2);
    //});

    $(".chart_type").click(function () {
        Clear_all()
        $(this).css("fill", '#000000');
        point = $('#' + $(this).attr('id')).find('svg')
        $(point).css("visibility", 'hidden');
        $('#'+$(this).attr('id') + '.chart_container').css("display", '');
    });

    function Clear_all() {
        $('#charts').find(".chart_type").each(function (index) {
            $(this).css("fill", '');
        });
        $('#charts').find(".chart_container").each(function (index) {
            $(this).css("display", 'none');
        });
    };


    $(document).ready(function () {
        $('#unique_class.chart_type').css("fill", '#000000');
        $('#unique_class.chart_container').css("display", '');
    });

});
