<script setup>
import {computed} from 'vue'
const props=defineProps({columns:{type:Array,required:true},rows:{type:Array,required:true},empty:{type:String,default:'暂无符合条件的记录'},minWidth:{type:Number,default:0}})
const totalWidth=computed(()=>props.minWidth||props.columns.reduce((n,c)=>n+(Number(c.width)||100),0))
</script>
<template>
 <div class="design-table-wrap"><table class="design-table" :style="{minWidth:totalWidth+'px'}"><colgroup><col v-for="col in columns" :key="col.key" :style="{width:col.width+'px'}"></colgroup>
 <thead><tr><th v-for="col in columns" :key="col.key" :class="{num:col.num}" scope="col">{{col.label}}</th></tr></thead>
 <tbody><tr v-for="(row,i) in rows" :key="row.id??i" :class="{selected:row.selected}"><td v-for="col in columns" :key="col.key" :class="{num:col.num}" :title="typeof row[col.key]==='string'?row[col.key]:undefined"><slot :name="'cell-'+col.key" :row="row" :value="row[col.key]" :index="i"><span class="cell-text">{{row[col.key]??'—'}}</span></slot></td></tr><tr v-if="!rows.length"><td :colspan="columns.length" class="empty-cell">{{empty}}</td></tr></tbody>
 </table></div>
</template>
